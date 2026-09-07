"""Outcome evaluation orchestration (§11: `actions` owns `Outcome`). No AI calls —
kept in its own module from the recommendation/approval workflow in `service.py` since
it's conceptually distinct (closing the loop after resolution, not driving toward it).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.outcome import compute_outcome
from app.models.action import Action
from app.models.issue import IssueStatus
from app.models.outcome import Outcome
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)


def evaluate_outcome(db: Session, action: Action) -> Outcome | None:
    """Returns None if the action hasn't been resolved yet — there's nothing to
    compare against before that point, not a failure.
    """
    if action.resolved_at is None:
        return None

    result = compute_outcome(db, action)

    outcome = db.execute(select(Outcome).where(Outcome.action_id == action.id)).scalar_one_or_none()
    if outcome is None:
        outcome = Outcome(action_id=action.id, before_period_start=result.before_period_start,
                           before_period_end=result.before_period_end, interpretation=result.interpretation)
        db.add(outcome)

    outcome.before_period_start = result.before_period_start
    outcome.before_period_end = result.before_period_end
    outcome.before_negative_count = result.before_negative_count
    outcome.after_period_start = result.after_period_start
    outcome.after_period_end = result.after_period_end
    outcome.after_negative_count = result.after_negative_count
    outcome.delta_pct = result.delta_pct
    outcome.interpretation = result.interpretation

    db.commit()
    db.refresh(outcome)
    return outcome


def evaluate_outcomes_for_business(
    db: Session, business_id: uuid.UUID, trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL
) -> ProcessingRun:
    """Evaluates (or re-evaluates) outcomes for every resolved-or-later action under a
    business. Safe to run repeatedly — an outcome that was `insufficient_data` last
    time will naturally resolve to a real verdict once enough time/data has passed.
    """
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.OUTCOME,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    candidate_statuses = (
        IssueStatus.ACTION_CREATED, IssueStatus.RESOLVED, IssueStatus.MONITORING, IssueStatus.CLOSED,
    )
    actions = db.execute(
        select(Action).where(Action.status.in_(candidate_statuses))
    ).scalars().all()

    evaluated = skipped = 0
    for action in actions:
        outcome = evaluate_outcome(db, action)
        if outcome is not None:
            evaluated += 1
        else:
            skipped += 1

    run.finished_at = datetime.now(UTC)
    run.reviews_in_scope = len(actions)
    run.reviews_succeeded = evaluated
    run.reviews_failed = 0
    run.status = ProcessingRunStatus.COMPLETED
    db.commit()

    return run
