import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.outcome_service import evaluate_outcome, evaluate_outcomes_for_business
from app.actions.schemas import ActionOut, ApproveActionRequest, OutcomeOut, RejectActionRequest
from app.actions.service import (
    approve_action,
    recommend_action,
    reject_action,
    resolve_action,
    submit_action_for_approval,
)
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.database import get_db
from app.models.action import Action
from app.models.issue import Issue
from app.models.outcome import Outcome
from app.models.processing_run import ProcessingRunTrigger
from app.models.user import User
from app.workflow.state_machine import InvalidTransitionError

router = APIRouter(tags=["actions"])


def _get_action_or_404(db: Session, action_id: uuid.UUID) -> Action:
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    return action


@router.post(
    "/issues/{issue_id}/actions/recommend",
    response_model=ActionOut,
    status_code=status.HTTP_201_CREATED,
)
def recommend_action_for_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> Action:
    """reviewed -> recommended. One Claude call (or a free deterministic-template
    fallback without an API key, §8 graceful degradation) drafts the recommendation;
    everything else — the transition, persistence, audit log — is deterministic.
    """
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")

    try:
        return recommend_action(db, issue, settings, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    business_id: uuid.UUID | None = None,
    issue_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Action]:
    query = select(Action)
    if business_id is not None:
        query = query.join(Issue, Issue.id == Action.issue_id).where(Issue.business_id == business_id)
    if issue_id is not None:
        query = query.where(Action.issue_id == issue_id)
    if status_filter is not None:
        query = query.where(Action.status == status_filter)
    query = query.order_by(Action.created_at.desc())
    return list(db.execute(query).scalars().all())


@router.get("/actions/{action_id}", response_model=ActionOut)
def get_action(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Action:
    return _get_action_or_404(db, action_id)


@router.post("/actions/{action_id}/submit-for-approval", response_model=ActionOut)
def submit_for_approval(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Action:
    action = _get_action_or_404(db, action_id)
    try:
        return submit_action_for_approval(db, action, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
def approve(
    action_id: uuid.UUID,
    payload: ApproveActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Action:
    """awaiting_approval -> approved -> action_created. Consequential and human-gated
    (§ kickoff spec: AI may recommend, it never autonomously executes)."""
    action = _get_action_or_404(db, action_id)
    try:
        return approve_action(
            db, action, approver=current_user.email,
            decision_note=payload.decision_note, modified_text=payload.modified_text,
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject(
    action_id: uuid.UUID,
    payload: RejectActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Action:
    action = _get_action_or_404(db, action_id)
    try:
        return reject_action(db, action, approver=current_user.email, decision_note=payload.decision_note)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/actions/{action_id}/resolve", response_model=ActionOut)
def resolve(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Action:
    action = _get_action_or_404(db, action_id)
    try:
        return resolve_action(db, action, actor=current_user.email)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/actions/{action_id}/evaluate-outcome", response_model=OutcomeOut)
def evaluate_action_outcome(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Outcome:
    """Deterministic before/after verdict (§7) — no AI call. Returns 409 if the action
    hasn't been resolved yet (nothing to compare against before that point).
    """
    action = _get_action_or_404(db, action_id)
    outcome = evaluate_outcome(db, action)
    if outcome is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Action has not been resolved yet")
    return outcome


@router.get("/actions/{action_id}/outcome", response_model=OutcomeOut)
def get_action_outcome(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Outcome:
    _get_action_or_404(db, action_id)
    outcome = db.execute(select(Outcome).where(Outcome.action_id == action_id)).scalar_one_or_none()
    if outcome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No outcome evaluated for this action yet")
    return outcome


class OutcomeEvaluationBatchResponse(BaseModel):
    processing_run_id: str
    status: str
    actions_in_scope: int
    evaluated: int


@router.post("/outcomes/evaluate", response_model=OutcomeEvaluationBatchResponse)
def evaluate_outcomes(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OutcomeEvaluationBatchResponse:
    """Re-evaluates outcomes for every resolved-or-later action under a business. Fully
    deterministic — safe to run on a schedule (§ Phase 10 stand-in).
    """
    run = evaluate_outcomes_for_business(db, business_id, trigger=ProcessingRunTrigger.MANUAL)
    return OutcomeEvaluationBatchResponse(
        processing_run_id=str(run.id),
        status=run.status,
        actions_in_scope=run.reviews_in_scope,
        evaluated=run.reviews_succeeded,
    )
