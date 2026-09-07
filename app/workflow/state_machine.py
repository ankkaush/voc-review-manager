"""Shared state-machine + audit-logging utility (§11: `workflow` module owns
`WorkflowEvent`, used by both `issues` and `actions`).

`Issue` and `Action` share one status vocabulary (§3: "same workflow enum as Issue") and
therefore one transition graph. This module is the single place that graph is defined —
neither `issues/` nor `actions/` should validate a transition on its own.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.issue import IssueStatus
from app.models.workflow_event import WorkflowEvent

# identified -> reviewed -> recommended -> awaiting_approval -> approved -> action_created
#   -> resolved -> monitoring -> closed, with a `rejected` branch available from any
# pre-approval state (a human can dismiss/reject at any point before it's approved).
ALLOWED_TRANSITIONS: dict[IssueStatus, set[IssueStatus]] = {
    IssueStatus.IDENTIFIED: {IssueStatus.REVIEWED, IssueStatus.REJECTED},
    IssueStatus.REVIEWED: {IssueStatus.RECOMMENDED, IssueStatus.REJECTED},
    IssueStatus.RECOMMENDED: {IssueStatus.AWAITING_APPROVAL, IssueStatus.REJECTED},
    IssueStatus.AWAITING_APPROVAL: {IssueStatus.APPROVED, IssueStatus.REJECTED},
    IssueStatus.APPROVED: {IssueStatus.ACTION_CREATED},
    IssueStatus.ACTION_CREATED: {IssueStatus.RESOLVED},
    IssueStatus.RESOLVED: {IssueStatus.MONITORING},
    IssueStatus.MONITORING: {IssueStatus.CLOSED},
    IssueStatus.REJECTED: set(),
    IssueStatus.CLOSED: set(),
}


def is_transition_allowed(from_state: IssueStatus, to_state: IssueStatus) -> bool:
    """Fail-fast pre-check (no logging) — use before doing expensive work (an AI call)
    that would be wasted if the entity isn't actually eligible for this transition.
    """
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


def _state_label(state: IssueStatus | str | None) -> str:
    """`status` columns are plain `String`, not a native enum (§3 ADR context), so a
    value freshly assigned in Python is an `IssueStatus` member while one read back
    after a DB round-trip is a plain `str` — both are valid and compare equal (str-enum
    mixin), but only the former has `.value`. Handle both explicitly rather than assume.
    """
    if state is None:
        return "none"
    return state.value if isinstance(state, IssueStatus) else state


class InvalidTransitionError(Exception):
    def __init__(self, entity_type: str, from_state, to_state):
        self.entity_type = entity_type
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Cannot transition {entity_type} from '{_state_label(from_state)}' "
            f"to '{_state_label(to_state)}'"
        )


def transition(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    from_state: IssueStatus | None,
    to_state: IssueStatus,
    actor: str,
    reason: str | None = None,
) -> WorkflowEvent:
    """Validates the transition and logs a `WorkflowEvent`. Does NOT set the entity's
    `status` field itself — the caller owns persisting that, immediately after this
    call succeeds, in the same transaction (§17 audit trail: the event and the state
    change must land together).

    `from_state=None` is allowed only for an entity's very first recorded state (e.g.
    issue creation) — there is no prior state to validate against.
    """
    if from_state is not None:
        allowed = ALLOWED_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise InvalidTransitionError(entity_type, from_state, to_state)

    event = WorkflowEvent(
        entity_type=entity_type,
        entity_id=str(entity_id),
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        reason=reason,
    )
    db.add(event)
    return event
