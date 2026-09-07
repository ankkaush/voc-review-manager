import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.issues.schemas import (
    DismissIssueRequest,
    InsightItem,
    IssueEvidenceResponse,
    IssueOut,
    MetricEvidenceItem,
    ReviewCitationItem,
    WorkflowEventItem,
)
from app.issues.service import (
    close_issue,
    detect_recurring_issues,
    dismiss_issue,
    monitor_issue,
    review_issue,
    update_trends_and_priorities,
)
from app.models.action import Action
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.insight import Insight
from app.models.issue import EvidenceType, Issue, IssueEvidence
from app.models.processing_run import ProcessingRunTrigger
from app.models.review import Review
from app.models.user import User
from app.models.workflow_event import WorkflowEvent
from app.workflow.state_machine import InvalidTransitionError

router = APIRouter(prefix="/issues", tags=["issues"])


class IssueDetectionResponse(BaseModel):
    processing_run_id: str
    status: str


@router.post("/detect", response_model=IssueDetectionResponse)
def run_issue_detection(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> IssueDetectionResponse:
    run = detect_recurring_issues(db, business_id, trigger=ProcessingRunTrigger.MANUAL)
    return IssueDetectionResponse(processing_run_id=str(run.id), status=run.status)


@router.post("/recompute-priority", response_model=IssueDetectionResponse)
def run_trend_and_priority_update(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> IssueDetectionResponse:
    """Recomputes trend classification + priority score for every open issue (Phase 5).
    Fully deterministic — no AI calls, safe to run as often as aggregation itself.
    """
    run = update_trends_and_priorities(db, business_id, trigger=ProcessingRunTrigger.MANUAL)
    return IssueDetectionResponse(processing_run_id=str(run.id), status=run.status)


@router.get("", response_model=list[IssueOut])
def list_issues(
    business_id: uuid.UUID,
    location_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Issue]:
    query = select(Issue).where(Issue.business_id == business_id)
    if location_id is not None:
        query = query.where(Issue.location_id == location_id)
    if status_filter is not None:
        query = query.where(Issue.status == status_filter)
    query = query.order_by(Issue.last_updated_at.desc())
    return list(db.execute(query).scalars().all())


@router.get("/{issue_id}", response_model=IssueOut)
def get_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Issue:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")
    return issue


@router.post("/{issue_id}/review", response_model=IssueOut)
def review(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """identified -> reviewed: a human marks the issue as looked at (§6 workflow)."""
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")
    try:
        return review_issue(db, issue, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{issue_id}/dismiss", response_model=IssueOut)
def dismiss(
    issue_id: uuid.UUID,
    payload: DismissIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """A human dismisses the issue before it reaches approval."""
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")
    try:
        return dismiss_issue(db, issue, actor=current_user.email, reason=payload.reason)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{issue_id}/monitor", response_model=IssueOut)
def monitor(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """resolved -> monitoring."""
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")
    try:
        return monitor_issue(db, issue, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{issue_id}/close", response_model=IssueOut)
def close(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """monitoring -> closed (terminal for v1)."""
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")
    try:
        return close_issue(db, issue, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{issue_id}/evidence", response_model=IssueEvidenceResponse)
def get_issue_evidence(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> IssueEvidenceResponse:
    """The provenance endpoint (§5, §C): answers "why is the system telling me this"
    by resolving Issue -> IssueEvidence -> the concrete AggregatePeriodMetric rows and
    representative Review rows behind it.
    """
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")

    evidence_rows = db.execute(
        select(IssueEvidence).where(IssueEvidence.issue_id == issue_id)
    ).scalars().all()

    metric_evidence = [e for e in evidence_rows if e.evidence_type == EvidenceType.METRIC]
    metric_ids = [e.aggregate_period_metric_id for e in metric_evidence]
    notes_by_metric_id = {e.aggregate_period_metric_id: e.note for e in metric_evidence}
    metrics = (
        db.execute(select(AggregatePeriodMetric).where(AggregatePeriodMetric.id.in_(metric_ids)))
        .scalars()
        .all()
        if metric_ids
        else []
    )

    review_ids = [e.review_id for e in evidence_rows if e.evidence_type == EvidenceType.REVIEW_CITATION]
    reviews = (
        db.execute(select(Review).where(Review.id.in_(review_ids))).scalars().all() if review_ids else []
    )

    latest_insight = db.execute(
        select(Insight).where(Insight.issue_id == issue_id).order_by(Insight.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    return IssueEvidenceResponse(
        issue=IssueOut.model_validate(issue),
        metrics=[
            MetricEvidenceItem(
                aggregate_period_metric_id=m.id,
                period_start=m.period_start,
                period_end=m.period_end,
                mention_count=m.mention_count,
                negative_count=m.negative_count,
                positive_count=m.positive_count,
                neutral_count=m.neutral_count,
                avg_rating=m.avg_rating,
                note=notes_by_metric_id.get(m.id),
            )
            for m in sorted(metrics, key=lambda m: m.period_start)
        ],
        review_citations=[
            ReviewCitationItem(review_id=r.id, text=r.text, rating=r.rating, submitted_at=r.submitted_at)
            for r in sorted(reviews, key=lambda r: r.submitted_at, reverse=True)
        ],
        latest_insight=(
            InsightItem(
                id=latest_insight.id,
                text=latest_insight.text,
                generation_method=latest_insight.generation_method,
                created_at=latest_insight.created_at,
            )
            if latest_insight is not None
            else None
        ),
    )


@router.get("/{issue_id}/audit", response_model=list[WorkflowEventItem])
def get_issue_audit_trail(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[WorkflowEvent]:
    """Complete audit trail (§17/§6 DoD): every transition for this issue AND for any
    Action created under it, merged in chronological order — "who did what, when."
    """
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")

    action_ids = [
        a.id for a in db.execute(select(Action).where(Action.issue_id == issue_id)).scalars().all()
    ]

    entity_ids = {str(issue_id)} | {str(a_id) for a_id in action_ids}
    events = db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.entity_id.in_(entity_ids))
        .order_by(WorkflowEvent.created_at)
    ).scalars().all()

    return list(events)
