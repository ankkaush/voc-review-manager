"""Taxonomy-based recurring-issue detection (§11: `issues` module owns `Issue`,
`IssueEvidence`; ADR-1: taxonomy-based grouping for v1, no clustering).

A (topic, aspect, location) combination is promoted to an `Issue` when it has enough
*weeks* of meaningfully elevated negative volume — not just a high running total, which
a chronic-but-minor complaint (see: the price/value negative control in the synthetic
dataset) can also accumulate over 26 weeks. This is deliberately simpler than Phase 5's
trend engine: it answers "is this recurring enough to track," not "is it accelerating."

Deterministic throughout — titles/descriptions are template text, not LLM output (that
starts in Phase 5 with grounded Insight synthesis).
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.issues.priority import compute_priority
from app.issues.trend import compute_trend
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.issue import EvidenceType, Issue, IssueEvidence, IssueStatus
from app.models.location import Location
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)
from app.models.review import Review
from app.models.review_analysis import ReviewAnalysis, ReviewAspect
from app.models.taxonomy import Aspect, Topic
from app.notifications.service import notify_new_high_priority_issue
from app.workflow.state_machine import transition

CLOSED_STATUSES = (IssueStatus.RESOLVED, IssueStatus.CLOSED, IssueStatus.REJECTED)

WEEKLY_NEGATIVE_THRESHOLD = 5
MIN_RECURRING_WEEKS = 2
MAX_REPRESENTATIVE_REVIEWS = 10
SEVERITY_ORDER = ["high", "medium", "low"]


def _find_or_create_issue(
    db: Session, business_id: uuid.UUID, location_id: uuid.UUID, topic_id: uuid.UUID, aspect_id: uuid.UUID
) -> tuple[Issue, bool]:
    existing = db.execute(
        select(Issue).where(
            Issue.business_id == business_id,
            Issue.location_id == location_id,
            Issue.topic_id == topic_id,
            Issue.aspect_id == aspect_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    topic = db.get(Topic, topic_id)
    aspect = db.get(Aspect, aspect_id)
    location = db.get(Location, location_id)

    issue = Issue(
        business_id=business_id,
        location_id=location_id,
        topic_id=topic_id,
        aspect_id=aspect_id,
        title=f"{aspect.label} complaints at {location.name}",
        description=(
            f"Recurring negative feedback about {aspect.label.lower()} "
            f"({topic.label.lower()}) identified at {location.name}."
        ),
        status=IssueStatus.IDENTIFIED,
    )
    db.add(issue)
    db.flush()

    transition(
        db,
        entity_type="issue",
        entity_id=issue.id,
        from_state=None,
        to_state=IssueStatus.IDENTIFIED,
        actor="system",
        reason="Promoted from recurring-issue detection",
    )
    return issue, True


def _attach_metric_evidence(db: Session, issue: Issue, metrics: list[AggregatePeriodMetric]) -> None:
    existing_metric_ids = {
        e.aggregate_period_metric_id
        for e in db.execute(
            select(IssueEvidence).where(
                IssueEvidence.issue_id == issue.id, IssueEvidence.evidence_type == EvidenceType.METRIC
            )
        ).scalars()
    }
    for metric in metrics:
        if metric.id in existing_metric_ids:
            continue
        db.add(
            IssueEvidence(
                issue_id=issue.id,
                aggregate_period_metric_id=metric.id,
                evidence_type=EvidenceType.METRIC,
                note=f"{metric.negative_count} negative mentions, week of {metric.period_start.isoformat()}",
            )
        )


def _attach_review_evidence(
    db: Session,
    issue: Issue,
    business_id: uuid.UUID,
    location_id: uuid.UUID,
    topic_id: uuid.UUID,
    aspect_id: uuid.UUID,
) -> None:
    existing_review_ids = {
        e.review_id
        for e in db.execute(
            select(IssueEvidence).where(
                IssueEvidence.issue_id == issue.id,
                IssueEvidence.evidence_type == EvidenceType.REVIEW_CITATION,
            )
        ).scalars()
    }

    already_linked = len(existing_review_ids)
    if already_linked >= MAX_REPRESENTATIVE_REVIEWS:
        return

    candidate_reviews = db.execute(
        select(Review)
        .join(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .join(ReviewAspect, ReviewAspect.review_analysis_id == ReviewAnalysis.id)
        .where(
            Review.business_id == business_id,
            Review.location_id == location_id,
            ReviewAspect.topic_id == topic_id,
            ReviewAspect.aspect_id == aspect_id,
            ReviewAspect.aspect_sentiment == "negative",
        )
        .order_by(Review.submitted_at.desc())
        .limit(MAX_REPRESENTATIVE_REVIEWS)
    ).scalars().all()

    for review in candidate_reviews:
        if len(existing_review_ids) >= MAX_REPRESENTATIVE_REVIEWS:
            break
        if review.id in existing_review_ids:
            continue
        db.add(
            IssueEvidence(
                issue_id=issue.id,
                review_id=review.id,
                evidence_type=EvidenceType.REVIEW_CITATION,
            )
        )
        existing_review_ids.add(review.id)


def _update_severity(
    db: Session,
    issue: Issue,
    business_id: uuid.UUID,
    location_id: uuid.UUID,
    topic_id: uuid.UUID,
    aspect_id: uuid.UUID,
) -> None:
    severities = {
        s
        for (s,) in db.execute(
            select(ReviewAspect.severity)
            .join(ReviewAnalysis, ReviewAnalysis.id == ReviewAspect.review_analysis_id)
            .join(Review, Review.id == ReviewAnalysis.review_id)
            .where(
                Review.business_id == business_id,
                Review.location_id == location_id,
                ReviewAspect.topic_id == topic_id,
                ReviewAspect.aspect_id == aspect_id,
                ReviewAspect.aspect_sentiment == "negative",
                ReviewAspect.severity.is_not(None),
            )
        )
    }
    for level in SEVERITY_ORDER:
        if level in severities:
            issue.severity = level
            return
    issue.severity = None


def detect_recurring_issues(
    db: Session, business_id: uuid.UUID, trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL
) -> ProcessingRun:
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.ISSUE_DETECTION,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    metrics = db.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business_id,
            AggregatePeriodMetric.location_id.is_not(None),
        )
    ).scalars().all()

    grouped: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID], list[AggregatePeriodMetric]] = defaultdict(list)
    for metric in metrics:
        grouped[(metric.location_id, metric.topic_id, metric.aspect_id)].append(metric)

    issues_created = issues_updated = 0

    for (location_id, topic_id, aspect_id), metric_rows in grouped.items():
        qualifying_weeks = [m for m in metric_rows if m.negative_count >= WEEKLY_NEGATIVE_THRESHOLD]
        if len(qualifying_weeks) < MIN_RECURRING_WEEKS:
            continue

        issue, created = _find_or_create_issue(db, business_id, location_id, topic_id, aspect_id)
        issues_created += created
        issues_updated += not created

        _attach_metric_evidence(db, issue, qualifying_weeks)
        _attach_review_evidence(db, issue, business_id, location_id, topic_id, aspect_id)
        _update_severity(db, issue, business_id, location_id, topic_id, aspect_id)

        if created:
            # Only a brand-new issue notifies — this detection pass runs repeatedly and
            # re-attaches evidence to already-known issues constantly, which isn't news.
            notify_new_high_priority_issue(db, issue)

    db.commit()

    run.finished_at = datetime.now(UTC)
    run.reviews_in_scope = len(grouped)
    run.reviews_succeeded = issues_created + issues_updated
    run.reviews_failed = 0
    run.status = ProcessingRunStatus.COMPLETED
    db.commit()

    return run


def update_trends_and_priorities(
    db: Session, business_id: uuid.UUID, trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL
) -> ProcessingRun:
    """Recomputes trend classification + priority score for every open issue (§8/§D).
    Deterministic and cheap — safe to run as often as aggregation itself; no AI calls.
    """
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.TREND,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    open_issues = db.execute(
        select(Issue).where(Issue.business_id == business_id, Issue.status.not_in(CLOSED_STATUSES))
    ).scalars().all()

    for issue in open_issues:
        trend = compute_trend(db, issue)
        issue.trend_direction = trend.direction
        issue.trend_change_pct = trend.change_pct

        priority = compute_priority(db, issue, trend)
        issue.priority_score = priority.score
        issue.priority_score_breakdown = priority.breakdown

    db.commit()

    run.finished_at = datetime.now(UTC)
    run.reviews_in_scope = len(open_issues)
    run.reviews_succeeded = len(open_issues)
    run.reviews_failed = 0
    run.status = ProcessingRunStatus.COMPLETED
    db.commit()

    return run


def review_issue(db: Session, issue: Issue, actor: str) -> Issue:
    """A human marks the issue as looked at (§6 workflow: identified -> reviewed)."""
    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.REVIEWED, actor=actor,
    )
    issue.status = IssueStatus.REVIEWED
    db.commit()
    return issue


def dismiss_issue(db: Session, issue: Issue, actor: str, reason: str | None = None) -> Issue:
    """A human dismisses the issue before it reaches approval (§6: identified/reviewed/
    recommended/awaiting_approval -> rejected). Does not cascade to any in-flight Action
    — reject the action directly if one already exists and needs to be stopped too.
    """
    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.REJECTED, actor=actor, reason=reason,
    )
    issue.status = IssueStatus.REJECTED
    db.commit()
    return issue


def monitor_issue(db: Session, issue: Issue, actor: str) -> Issue:
    """resolved -> monitoring: the approved action has been resolved; Phase 7's outcome
    tracking will observe whether the underlying metric actually improves during this
    state.
    """
    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.MONITORING, actor=actor,
    )
    issue.status = IssueStatus.MONITORING
    db.commit()
    return issue


def close_issue(db: Session, issue: Issue, actor: str) -> Issue:
    """monitoring -> closed: terminal state for v1. Known limitation, deliberately out
    of scope: `_find_or_create_issue` matches purely on (business, location, topic,
    aspect) regardless of status, so if the same pattern keeps recurring after closure,
    a later detection run will find and re-attach evidence to this closed row rather
    than opening a new one. Reopening/re-triage logic is a documented future
    enhancement, not a Phase 6 requirement.
    """
    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.CLOSED, actor=actor,
    )
    issue.status = IssueStatus.CLOSED
    db.commit()
    return issue
