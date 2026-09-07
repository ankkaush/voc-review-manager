"""Action recommendation + human approval workflow (§11: `actions` owns `Action`,
`ActionApproval`; §D: "AI for interpretation and judgment; deterministic systems for
control and execution" — the AI call here only drafts text, every state transition and
the decision to act on it are deterministic and human-gated.
"""

import logging
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.actions.recommender import (
    ACTION_RECOMMENDATION_TOOL_NAME,
    ACTION_RECOMMENDATION_TOOL_SCHEMA,
    build_action_recommendation_prompt,
    deterministic_template_recommendation,
)
from app.actions.schemas import ActionRecommendationResult
from app.analysis.claude_client import call_claude_tool
from app.config import Settings
from app.core.retry import TransientError
from app.insights.evidence import build_insight_evidence
from app.models.action import Action, ActionType
from app.models.action_approval import ActionApproval, ApprovalDecision
from app.models.ai_invocation import AIInvocation, AIOperation
from app.models.issue import Issue, IssueStatus
from app.notifications.service import notify_action_pending_approval
from app.workflow.state_machine import InvalidTransitionError, is_transition_allowed, transition

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


def _log_invocation(
    db: Session,
    issue: Issue,
    settings: Settings,
    *,
    latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    validation_passed: bool,
    error_type: str | None,
) -> AIInvocation:
    invocation = AIInvocation(
        operation=AIOperation.ACTION_RECOMMENDATION,
        model=settings.analysis_model,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate_usd=None,
        validation_passed=validation_passed,
        error_type=error_type,
        input_ref=str(issue.id),
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)
    return invocation


def recommend_action(db: Session, issue: Issue, settings: Settings, actor: str) -> Action:
    """reviewed -> recommended. Raises InvalidTransitionError if the issue isn't
    `reviewed` yet — checked before spending any API call.
    """
    if not is_transition_allowed(issue.status, IssueStatus.RECOMMENDED):
        raise InvalidTransitionError("issue", issue.status, IssueStatus.RECOMMENDED)

    evidence = build_insight_evidence(db, issue)
    ai_invocation_id = None

    if not settings.anthropic_api_key:
        recommended_text = deterministic_template_recommendation(evidence)
    else:
        prompt = build_action_recommendation_prompt(evidence)
        try:
            response = call_claude_tool(
                prompt, ACTION_RECOMMENDATION_TOOL_SCHEMA, ACTION_RECOMMENDATION_TOOL_NAME,
                settings.analysis_model, settings,
            )
        except TransientError as exc:
            logger.warning(
                "Action recommendation provider error",
                extra={"context": {"issue_id": str(issue.id), "error": str(exc)}},
            )
            raise

        try:
            result = ActionRecommendationResult.model_validate(response.raw_input)
        except ValidationError as exc:
            _log_invocation(
                db, issue, settings,
                latency_ms=response.latency_ms, prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                validation_passed=False, error_type="validation_error",
            )
            raise ValueError(f"Action recommendation produced invalid output: {exc}") from exc

        invocation = _log_invocation(
            db, issue, settings,
            latency_ms=response.latency_ms, prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            validation_passed=True, error_type=None,
        )
        recommended_text = result.recommended_action
        ai_invocation_id = invocation.id

    action = Action(
        issue_id=issue.id,
        type=ActionType.OPERATIONAL_TASK,
        recommended_text=recommended_text,
        ai_invocation_id=ai_invocation_id,
        status=IssueStatus.RECOMMENDED,
    )
    db.add(action)
    db.flush()

    transition(
        db, entity_type="action", entity_id=action.id,
        from_state=None, to_state=IssueStatus.RECOMMENDED, actor=actor,
    )
    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.RECOMMENDED, actor=actor,
    )
    issue.status = IssueStatus.RECOMMENDED
    db.commit()
    db.refresh(action)
    return action


def submit_action_for_approval(db: Session, action: Action, actor: str) -> Action:
    """recommended -> awaiting_approval, cascading the parent Issue."""
    issue = db.get(Issue, action.issue_id)

    transition(
        db, entity_type="action", entity_id=action.id,
        from_state=action.status, to_state=IssueStatus.AWAITING_APPROVAL, actor=actor,
    )
    action.status = IssueStatus.AWAITING_APPROVAL

    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.AWAITING_APPROVAL, actor=actor,
    )
    issue.status = IssueStatus.AWAITING_APPROVAL
    db.commit()

    notify_action_pending_approval(db, action, issue)

    db.refresh(action)
    return action


def approve_action(
    db: Session,
    action: Action,
    approver: str,
    decision_note: str | None = None,
    modified_text: str | None = None,
) -> Action:
    """awaiting_approval -> approved -> action_created, in one human decision (§ kickoff
    spec: "Once approved, deterministic application logic can create the appropriate
    task"). The original AI-recommended text is never overwritten — an approver's edit
    is preserved separately on the `ActionApproval` row (`modified_text`), so the audit
    trail keeps both what was proposed and what was actually approved.
    """
    issue = db.get(Issue, action.issue_id)
    if not is_transition_allowed(action.status, IssueStatus.APPROVED):
        raise InvalidTransitionError("action", action.status, IssueStatus.APPROVED)

    decision = ApprovalDecision.MODIFIED if modified_text else ApprovalDecision.APPROVED
    db.add(
        ActionApproval(
            action_id=action.id, decision=decision, approver=approver,
            decision_note=decision_note, modified_text=modified_text,
        )
    )

    for to_state in (IssueStatus.APPROVED, IssueStatus.ACTION_CREATED):
        transition(
            db, entity_type="action", entity_id=action.id,
            from_state=action.status, to_state=to_state, actor=approver,
        )
        action.status = to_state
        transition(
            db, entity_type="issue", entity_id=issue.id,
            from_state=issue.status, to_state=to_state, actor=approver,
        )
        issue.status = to_state

    db.commit()
    db.refresh(action)
    return action


def reject_action(db: Session, action: Action, approver: str, decision_note: str | None = None) -> Action:
    """awaiting_approval -> rejected, cascading the parent Issue."""
    issue = db.get(Issue, action.issue_id)
    if not is_transition_allowed(action.status, IssueStatus.REJECTED):
        raise InvalidTransitionError("action", action.status, IssueStatus.REJECTED)

    db.add(
        ActionApproval(
            action_id=action.id,
            decision=ApprovalDecision.REJECTED,
            approver=approver,
            decision_note=decision_note,
        )
    )

    transition(
        db, entity_type="action", entity_id=action.id,
        from_state=action.status, to_state=IssueStatus.REJECTED, actor=approver, reason=decision_note,
    )
    action.status = IssueStatus.REJECTED

    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.REJECTED, actor=approver, reason=decision_note,
    )
    issue.status = IssueStatus.REJECTED

    db.commit()
    db.refresh(action)
    return action


def resolve_action(db: Session, action: Action, actor: str) -> Action:
    """action_created -> resolved, cascading the parent Issue. Sets `resolved_at` —
    Phase 7's outcome tracking anchors its before/after comparison on this timestamp.
    """
    issue = db.get(Issue, action.issue_id)

    transition(
        db, entity_type="action", entity_id=action.id,
        from_state=action.status, to_state=IssueStatus.RESOLVED, actor=actor,
    )
    action.status = IssueStatus.RESOLVED
    action.resolved_at = datetime.now(UTC)

    transition(
        db, entity_type="issue", entity_id=issue.id,
        from_state=issue.status, to_state=IssueStatus.RESOLVED, actor=actor,
    )
    issue.status = IssueStatus.RESOLVED

    db.commit()
    db.refresh(action)
    return action
