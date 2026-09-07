from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates, week_start
from app.issues.service import detect_recurring_issues
from app.models.issue import EvidenceType, Issue, IssueEvidence
from tests.factories import create_analyzed_review, create_business_and_location

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=30)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _seed_wait_time_pattern(db: Session, business, location) -> None:
    """Mirrors the synthetic dataset's seeded emerging issue (§7): a persistently
    elevated wait-time complaint rate, well above the recurring-issue threshold.
    """
    weekly_counts = [3, 3, 5, 7, 9, 18]  # last 4 weeks all cross WEEKLY_NEGATIVE_THRESHOLD=5
    for week_offset, count in enumerate(weekly_counts):
        for i in range(count):
            create_analyzed_review(
                db, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="medium" if week_offset < 4 else "high",
                rating=1, text=f"Waited far too long, week {week_offset} review {i}",
            )


def _seed_price_negative_control(db: Session, business, location) -> None:
    """Mirrors the synthetic dataset's flat negative control (§7): consistently low
    weekly volume that must NOT be promoted to an Issue, even summed over many weeks.
    """
    for week_offset in range(10):
        for i in range(2):  # well under WEEKLY_NEGATIVE_THRESHOLD=5 every single week
            create_analyzed_review(
                db, business, location, submitted_at=_week(week_offset),
                topic_key="price", aspect_key="price_value", aspect_sentiment="negative",
                severity="low", rating=3, text=f"A bit pricey, week {week_offset} review {i}",
            )


@pytest.mark.integration
def test_recurring_pattern_is_promoted_to_an_issue(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    _seed_wait_time_pattern(db_session, business, location)

    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    issue = db_session.execute(
        select(Issue).where(Issue.business_id == business.id, Issue.location_id == location.id)
    ).scalar_one()

    assert issue.title == f"Wait Time complaints at {location.name}"
    assert issue.severity == "high"  # highest severity present among qualifying weeks wins

    evidence = db_session.execute(
        select(IssueEvidence).where(IssueEvidence.issue_id == issue.id)
    ).scalars().all()
    metric_evidence = [e for e in evidence if e.evidence_type == EvidenceType.METRIC]
    review_evidence = [e for e in evidence if e.evidence_type == EvidenceType.REVIEW_CITATION]

    # Exactly the 4 qualifying weeks (negative_count >= 5) are cited as metric evidence.
    assert len(metric_evidence) == 4
    # Representative reviews are capped, not every one of the 45 negative reviews.
    assert 0 < len(review_evidence) <= 10


@pytest.mark.integration
def test_flat_negative_control_is_not_promoted(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    _seed_price_negative_control(db_session, business, location)

    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    existing = db_session.execute(
        select(Issue).where(Issue.business_id == business.id, Issue.location_id == location.id)
    ).scalar_one_or_none()
    assert existing is None


@pytest.mark.integration
def test_detect_recurring_issues_is_idempotent(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    _seed_wait_time_pattern(db_session, business, location)
    compute_weekly_aggregates(db_session, business.id)

    detect_recurring_issues(db_session, business.id)
    detect_recurring_issues(db_session, business.id)  # re-run, e.g. a later scheduled pass

    issues = db_session.execute(
        select(Issue).where(Issue.business_id == business.id, Issue.location_id == location.id)
    ).scalars().all()
    assert len(issues) == 1  # not duplicated

    evidence = db_session.execute(
        select(IssueEvidence).where(IssueEvidence.issue_id == issues[0].id)
    ).scalars().all()
    metric_evidence_ids = [
        e.aggregate_period_metric_id for e in evidence if e.evidence_type == EvidenceType.METRIC
    ]
    assert len(metric_evidence_ids) == len(set(metric_evidence_ids))  # no duplicate evidence rows


@pytest.mark.integration
def test_issue_evidence_endpoint_via_service_layer_is_traceable(db_session: Session) -> None:
    """A cheaper proxy for the full provenance API test (§5): confirms the evidence
    chain built by detect_recurring_issues actually resolves to real metric/review rows.
    """
    business, location = create_business_and_location(db_session)
    _seed_wait_time_pattern(db_session, business, location)
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    issue = db_session.execute(
        select(Issue).where(Issue.business_id == business.id, Issue.location_id == location.id)
    ).scalar_one()
    evidence = db_session.execute(
        select(IssueEvidence).where(IssueEvidence.issue_id == issue.id)
    ).scalars().all()

    metric_evidence = [e for e in evidence if e.evidence_type == EvidenceType.METRIC]
    review_evidence = [e for e in evidence if e.evidence_type == EvidenceType.REVIEW_CITATION]
    assert all(e.aggregate_period_metric_id is not None for e in metric_evidence)
    assert all(e.review_id is not None for e in review_evidence)
