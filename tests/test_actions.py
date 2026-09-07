"""End-to-end human-approval workflow tests (Phase 6 DoD): an issue walked
identified -> ... -> closed via service calls, with a complete audit trail, and
invalid transitions correctly rejected. The Claude call in `recommend_action` is
mocked — this suite verifies workflow correctness, not AI prose quality (that's
covered by tests/test_insights.py's equivalent mocked coverage for the same client).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.service import (
    approve_action,
    recommend_action,
    reject_action,
    resolve_action,
    submit_action_for_approval,
)
from app.aggregation.service import compute_weekly_aggregates, week_start
from app.analysis.claude_client import ClaudeToolResponse
from app.config import get_settings
from app.issues.service import (
    close_issue,
    detect_recurring_issues,
    dismiss_issue,
    monitor_issue,
    review_issue,
)
from app.models.action import Action
from app.models.action_approval import ActionApproval, ApprovalDecision
from app.models.issue import Issue, IssueStatus
from app.models.workflow_event import WorkflowEvent
from app.workflow.state_machine import InvalidTransitionError
from tests.factories import create_analyzed_review, create_business_and_location

settings = get_settings()

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=60)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _seeded_issue(db: Session) -> Issue:
    business, location = create_business_and_location(db)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db, business.id)
    detect_recurring_issues(db, business.id)
    return db.execute(select(Issue).where(Issue.business_id == business.id)).scalar_one()


def _mock_recommendation(text: str) -> ClaudeToolResponse:
    return ClaudeToolResponse(
        raw_input={"recommended_action": text},
        model="claude-haiku-4-5-20251001", prompt_tokens=150, completion_tokens=30, latency_ms=200,
    )


@pytest.mark.integration
def test_full_happy_path_identified_to_closed_with_complete_audit_trail(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    assert issue.status == IssueStatus.IDENTIFIED

    review_issue(db_session, issue, actor="manager@example.com")
    assert issue.status == IssueStatus.REVIEWED

    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})
    mock = _mock_recommendation("Review peak-hour staffing and kitchen throughput at this location.")
    with patch("app.actions.service.call_claude_tool", return_value=mock):
        action = recommend_action(db_session, issue, settings_with_key, actor="manager@example.com")

    assert issue.status == IssueStatus.RECOMMENDED
    assert action.status == IssueStatus.RECOMMENDED
    assert action.recommended_text == "Review peak-hour staffing and kitchen throughput at this location."

    submit_action_for_approval(db_session, action, actor="manager@example.com")
    assert issue.status == IssueStatus.AWAITING_APPROVAL
    assert action.status == IssueStatus.AWAITING_APPROVAL

    approve_action(
        db_session, action, approver="director@example.com", decision_note="Approved, please proceed."
    )
    assert issue.status == IssueStatus.ACTION_CREATED
    assert action.status == IssueStatus.ACTION_CREATED

    approval = db_session.execute(
        select(ActionApproval).where(ActionApproval.action_id == action.id)
    ).scalar_one()
    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.approver == "director@example.com"

    resolve_action(db_session, action, actor="manager@example.com")
    assert issue.status == IssueStatus.RESOLVED
    assert action.status == IssueStatus.RESOLVED
    assert action.resolved_at is not None

    monitor_issue(db_session, issue, actor="manager@example.com")
    assert issue.status == IssueStatus.MONITORING

    close_issue(db_session, issue, actor="manager@example.com")
    assert issue.status == IssueStatus.CLOSED

    # Complete audit trail: every hop for both the issue and its action is recorded.
    issue_events = db_session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.entity_id == str(issue.id))
        .order_by(WorkflowEvent.created_at)
    ).scalars().all()
    issue_path = [e.to_state for e in issue_events]
    assert issue_path == [
        IssueStatus.IDENTIFIED, IssueStatus.REVIEWED, IssueStatus.RECOMMENDED,
        IssueStatus.AWAITING_APPROVAL, IssueStatus.APPROVED, IssueStatus.ACTION_CREATED,
        IssueStatus.RESOLVED, IssueStatus.MONITORING, IssueStatus.CLOSED,
    ]
    assert all(e.actor for e in issue_events)  # every hop attributes an actor

    action_events = db_session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.entity_id == str(action.id))
        .order_by(WorkflowEvent.created_at)
    ).scalars().all()
    action_path = [e.to_state for e in action_events]
    assert action_path == [
        IssueStatus.RECOMMENDED, IssueStatus.AWAITING_APPROVAL,
        IssueStatus.APPROVED, IssueStatus.ACTION_CREATED, IssueStatus.RESOLVED,
    ]


@pytest.mark.integration
def test_recommend_action_rejected_when_issue_not_reviewed(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    assert issue.status == IssueStatus.IDENTIFIED  # never reviewed

    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})
    with pytest.raises(InvalidTransitionError):
        recommend_action(db_session, issue, settings_with_key, actor="manager@example.com")

    # No Action was created, no wasted API call attempted.
    existing = db_session.execute(select(Action).where(Action.issue_id == issue.id)).scalar_one_or_none()
    assert existing is None


@pytest.mark.integration
def test_approving_an_already_rejected_action_is_rejected(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    review_issue(db_session, issue, actor="manager@example.com")

    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})
    with patch("app.actions.service.call_claude_tool", return_value=_mock_recommendation("Do something.")):
        action = recommend_action(db_session, issue, settings_with_key, actor="manager@example.com")

    submit_action_for_approval(db_session, action, actor="manager@example.com")
    reject_action(db_session, action, approver="director@example.com", decision_note="Not worth pursuing.")
    assert action.status == IssueStatus.REJECTED
    assert issue.status == IssueStatus.REJECTED

    with pytest.raises(InvalidTransitionError):
        approve_action(db_session, action, approver="director@example.com")

    # Rejecting didn't spuriously create a second ActionApproval or corrupt state.
    approvals = db_session.execute(
        select(ActionApproval).where(ActionApproval.action_id == action.id)
    ).scalars().all()
    assert len(approvals) == 1
    assert action.status == IssueStatus.REJECTED  # unchanged by the failed approve attempt


@pytest.mark.integration
def test_dismiss_issue_before_approval(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    dismiss_issue(db_session, issue, actor="manager@example.com", reason="Not a real problem.")
    assert issue.status == IssueStatus.REJECTED

    events = db_session.execute(
        select(WorkflowEvent).where(WorkflowEvent.entity_id == str(issue.id))
    ).scalars().all()
    assert any(e.reason == "Not a real problem." for e in events)


@pytest.mark.unit
def test_dismiss_already_closed_issue_is_rejected(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    dismiss_issue(db_session, issue, actor="manager@example.com")
    assert issue.status == IssueStatus.REJECTED

    with pytest.raises(InvalidTransitionError):
        dismiss_issue(db_session, issue, actor="manager@example.com")


@pytest.mark.integration
def test_approve_with_modified_text_preserves_original_recommendation(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    review_issue(db_session, issue, actor="manager@example.com")

    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})
    original_text = "Review staffing levels."
    with patch("app.actions.service.call_claude_tool", return_value=_mock_recommendation(original_text)):
        action = recommend_action(db_session, issue, settings_with_key, actor="manager@example.com")

    submit_action_for_approval(db_session, action, actor="manager@example.com")
    approve_action(
        db_session, action, approver="director@example.com",
        modified_text="Review staffing levels AND kitchen throughput.",
    )

    # The AI's original draft is never overwritten...
    assert action.recommended_text == original_text
    # ...the approver's edit lives on the approval record instead.
    approval = db_session.execute(
        select(ActionApproval).where(ActionApproval.action_id == action.id)
    ).scalar_one()
    assert approval.decision == ApprovalDecision.MODIFIED
    assert approval.modified_text == "Review staffing levels AND kitchen throughput."
