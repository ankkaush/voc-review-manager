"""Outcome tracking tests (Phase 7 DoD): the seeded post-action-improvement scenario
produces a correct Outcome row and verdict. Fully deterministic — no AI calls, no mocks
needed anywhere in this suite.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.actions.outcome_service import evaluate_outcome, evaluate_outcomes_for_business
from app.aggregation.service import compute_weekly_aggregates, week_start
from app.models.action import Action, ActionType
from app.models.issue import IssueStatus
from app.models.outcome import Outcome, OutcomeInterpretation
from tests.factories import create_analyzed_review, create_business_and_location

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=20)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _make_resolved_action(
    db: Session, business, location, topic_key: str, aspect_key: str, resolved_week_offset: int
):
    from sqlalchemy import select

    from app.issues.service import _find_or_create_issue  # internal helper reused for test setup
    from app.models.taxonomy import Aspect, Topic

    topic = db.execute(select(Topic).where(Topic.key == topic_key)).scalar_one()
    aspect = db.execute(
        select(Aspect).where(Aspect.topic_id == topic.id, Aspect.key == aspect_key)
    ).scalar_one()
    issue, _ = _find_or_create_issue(db, business.id, location.id, topic.id, aspect.id)
    db.commit()

    action = Action(
        issue_id=issue.id, type=ActionType.OPERATIONAL_TASK, recommended_text="Fix it.",
        status=IssueStatus.ACTION_CREATED, resolved_at=_week(resolved_week_offset) + timedelta(days=1),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return issue, action


@pytest.mark.unit
def test_outcome_improved_after_seeded_reduction(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    # Weeks 0-3: elevated negative volume (before). Action resolves during week 4 — the
    # window excludes the resolution week itself on both sides (a clean gap, since that
    # week is a mix of pre/post and shouldn't be attributed to either side).
    for w in range(4):
        for i in range(10):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="cleanliness", aspect_key="cleanliness_general",
                aspect_sentiment="negative", rating=2, text=f"Dirty tables, week {w} item {i}",
            )
    # Weeks 5-8 (after resolution): sharply reduced negative volume, but reviews still
    # exist (so this reads as genuine improvement, not "no data").
    for w in range(5, 9):
        for i in range(2):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="cleanliness", aspect_key="cleanliness_general",
                aspect_sentiment="negative", rating=4, text=f"Much cleaner now, week {w} item {i}",
            )
        create_analyzed_review(
            db_session, business, location, submitted_at=_week(w),
            topic_key="cleanliness", aspect_key="cleanliness_general",
            aspect_sentiment="positive", rating=5, text=f"Spotless, week {w}",
        )

    compute_weekly_aggregates(db_session, business.id)
    _, action = _make_resolved_action(db_session, business, location, "cleanliness", "cleanliness_general", 4)

    outcome = evaluate_outcome(db_session, action)

    assert outcome is not None
    assert outcome.before_negative_count == 40
    assert outcome.after_negative_count == 8
    assert outcome.delta_pct == pytest.approx(-80.0)
    assert outcome.interpretation == OutcomeInterpretation.IMPROVED


@pytest.mark.unit
def test_outcome_worsened_when_negative_volume_increases_after(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    for w in range(4):
        for i in range(3):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                rating=2, text=f"Slow, week {w} item {i}",
            )
    for w in range(5, 9):
        for i in range(10):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                rating=1, text=f"Even slower now, week {w} item {i}",
            )

    compute_weekly_aggregates(db_session, business.id)
    _, action = _make_resolved_action(db_session, business, location, "service", "wait_time", 4)

    outcome = evaluate_outcome(db_session, action)

    assert outcome.interpretation == OutcomeInterpretation.WORSENED
    assert outcome.delta_pct > 30


@pytest.mark.unit
def test_outcome_no_significant_change(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    for w in range(9):
        for i in range(5):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="price", aspect_key="price_value", aspect_sentiment="negative",
                rating=3, text=f"A bit pricey, week {w} item {i}",
            )

    compute_weekly_aggregates(db_session, business.id)
    _, action = _make_resolved_action(db_session, business, location, "price", "price_value", 4)

    outcome = evaluate_outcome(db_session, action)

    assert outcome.interpretation == OutcomeInterpretation.NO_SIGNIFICANT_CHANGE
    assert abs(outcome.delta_pct) < 30


@pytest.mark.unit
def test_outcome_insufficient_data_when_no_reviews_after_resolution(db_session: Session) -> None:
    """Distinguishes "no data yet" from "genuine improvement" — both would show
    after_negative_count effectively absent, but only one is a real verdict (§7).
    """
    business, location = create_business_and_location(db_session)

    for w in range(4):
        for i in range(10):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="cleanliness", aspect_key="cleanliness_general",
                aspect_sentiment="negative", rating=2, text=f"Dirty, week {w} item {i}",
            )
    # No reviews at all in weeks 5-8 (the after-period) — action resolved too recently
    # relative to available data.

    compute_weekly_aggregates(db_session, business.id)
    _, action = _make_resolved_action(db_session, business, location, "cleanliness", "cleanliness_general", 4)

    outcome = evaluate_outcome(db_session, action)

    assert outcome.interpretation == OutcomeInterpretation.INSUFFICIENT_DATA
    assert outcome.after_negative_count is None
    assert outcome.delta_pct is None
    assert outcome.before_negative_count == 40  # before-period math still ran correctly


@pytest.mark.unit
def test_evaluate_outcome_returns_none_for_unresolved_action(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    _, action = _make_resolved_action(db_session, business, location, "price", "price_value", 4)
    action.resolved_at = None
    db_session.commit()

    assert evaluate_outcome(db_session, action) is None


@pytest.mark.unit
def test_evaluate_outcome_upserts_in_place_on_rerun(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for w in range(4):
        for i in range(10):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(w),
                topic_key="cleanliness", aspect_key="cleanliness_general",
                aspect_sentiment="negative", rating=2, text=f"Dirty, week {w} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    _, action = _make_resolved_action(db_session, business, location, "cleanliness", "cleanliness_general", 4)

    first = evaluate_outcome(db_session, action)
    second = evaluate_outcome(db_session, action)

    assert first.id == second.id  # same row, updated in place, not duplicated
    from sqlalchemy import select

    all_rows = db_session.execute(select(Outcome).where(Outcome.action_id == action.id)).scalars().all()
    assert len(all_rows) == 1


@pytest.mark.integration
def test_evaluate_outcomes_for_business_processes_only_resolved_or_later_actions(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for w in range(4):
        create_analyzed_review(
            db_session, business, location, submitted_at=_week(w),
            topic_key="price", aspect_key="price_value", aspect_sentiment="negative", rating=3,
        )
    compute_weekly_aggregates(db_session, business.id)

    from sqlalchemy import select as sa_select

    from app.issues.service import _find_or_create_issue
    from app.models.taxonomy import Aspect, Topic

    topic = db_session.execute(sa_select(Topic).where(Topic.key == "price")).scalar_one()
    aspect = db_session.execute(
        sa_select(Aspect).where(Aspect.topic_id == topic.id, Aspect.key == "price_value")
    ).scalar_one()
    issue, _ = _find_or_create_issue(db_session, business.id, location.id, topic.id, aspect.id)
    db_session.commit()

    unresolved_action = Action(
        issue_id=issue.id, type=ActionType.OPERATIONAL_TASK, recommended_text="x",
        status=IssueStatus.AWAITING_APPROVAL,
    )
    db_session.add(unresolved_action)
    db_session.commit()

    run = evaluate_outcomes_for_business(db_session, business.id)

    assert run.status == "completed"
    assert run.reviews_in_scope == 0  # unresolved action isn't in a candidate status at all
    assert run.reviews_succeeded == 0
