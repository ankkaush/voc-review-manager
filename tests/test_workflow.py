"""Tests for the shared state-machine validator itself (§11 `workflow` module)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.issue import IssueStatus
from app.models.workflow_event import WorkflowEvent
from app.workflow.state_machine import InvalidTransitionError, is_transition_allowed, transition


@pytest.mark.unit
def test_valid_transition_is_allowed_and_logged(db_session: Session) -> None:
    entity_id = uuid.uuid4()
    event = transition(
        db_session, entity_type="issue", entity_id=entity_id,
        from_state=IssueStatus.IDENTIFIED, to_state=IssueStatus.REVIEWED, actor="test@example.com",
    )
    db_session.commit()

    assert event.from_state == IssueStatus.IDENTIFIED
    assert event.to_state == IssueStatus.REVIEWED

    stored = db_session.execute(
        select(WorkflowEvent).where(WorkflowEvent.entity_id == str(entity_id))
    ).scalar_one()
    assert stored.actor == "test@example.com"


@pytest.mark.unit
def test_invalid_transition_is_rejected_and_not_logged(db_session: Session) -> None:
    entity_id = uuid.uuid4()
    with pytest.raises(InvalidTransitionError):
        transition(
            db_session, entity_type="issue", entity_id=entity_id,
            from_state=IssueStatus.IDENTIFIED, to_state=IssueStatus.RESOLVED, actor="test@example.com",
        )

    existing = db_session.execute(
        select(WorkflowEvent).where(WorkflowEvent.entity_id == str(entity_id))
    ).scalar_one_or_none()
    assert existing is None


@pytest.mark.unit
def test_terminal_states_allow_no_further_transitions(db_session: Session) -> None:
    assert is_transition_allowed(IssueStatus.CLOSED, IssueStatus.IDENTIFIED) is False
    assert is_transition_allowed(IssueStatus.REJECTED, IssueStatus.REVIEWED) is False


@pytest.mark.unit
def test_initial_state_transition_from_none_is_allowed(db_session: Session) -> None:
    entity_id = uuid.uuid4()
    event = transition(
        db_session, entity_type="issue", entity_id=entity_id,
        from_state=None, to_state=IssueStatus.IDENTIFIED, actor="system",
    )
    db_session.commit()
    assert event.from_state is None
    assert event.to_state == IssueStatus.IDENTIFIED


@pytest.mark.unit
def test_full_happy_path_graph_is_walkable() -> None:
    """The exact chain the kickoff spec names: identified -> ... -> closed."""
    path = [
        IssueStatus.IDENTIFIED,
        IssueStatus.REVIEWED,
        IssueStatus.RECOMMENDED,
        IssueStatus.AWAITING_APPROVAL,
        IssueStatus.APPROVED,
        IssueStatus.ACTION_CREATED,
        IssueStatus.RESOLVED,
        IssueStatus.MONITORING,
        IssueStatus.CLOSED,
    ]
    for from_state, to_state in zip(path, path[1:], strict=False):
        assert is_transition_allowed(from_state, to_state), f"{from_state} -> {to_state} should be allowed"


@pytest.mark.unit
def test_reject_branch_reachable_from_every_pre_approval_state() -> None:
    for state in (
        IssueStatus.IDENTIFIED,
        IssueStatus.REVIEWED,
        IssueStatus.RECOMMENDED,
        IssueStatus.AWAITING_APPROVAL,
    ):
        assert is_transition_allowed(state, IssueStatus.REJECTED)
