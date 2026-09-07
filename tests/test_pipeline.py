"""Cron vs. manual equivalence (Phase 10 §10 DoD): a scheduled run must produce the
same result as the same call made manually through the API — the trigger is metadata
for the audit trail, not a branch in the logic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates, week_start
from app.issues.service import detect_recurring_issues
from app.models.processing_run import ProcessingRunTrigger
from tests.factories import create_analyzed_review, create_business_and_location

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=80)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _seed_recurring_pattern(db_session: Session):
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    return business, location


@pytest.mark.integration
def test_cron_trigger_produces_same_results_as_manual(db_session: Session) -> None:
    manual_business, _ = _seed_recurring_pattern(db_session)
    cron_business, _ = _seed_recurring_pattern(db_session)

    manual_agg = compute_weekly_aggregates(
        db_session, manual_business.id, trigger=ProcessingRunTrigger.MANUAL
    )
    cron_agg = compute_weekly_aggregates(
        db_session, cron_business.id, trigger=ProcessingRunTrigger.CRON
    )

    assert manual_agg.trigger == ProcessingRunTrigger.MANUAL
    assert cron_agg.trigger == ProcessingRunTrigger.CRON
    assert manual_agg.status == cron_agg.status
    assert manual_agg.reviews_in_scope == cron_agg.reviews_in_scope

    manual_issue_run = detect_recurring_issues(
        db_session, manual_business.id, trigger=ProcessingRunTrigger.MANUAL
    )
    cron_issue_run = detect_recurring_issues(
        db_session, cron_business.id, trigger=ProcessingRunTrigger.CRON
    )

    assert manual_issue_run.status == cron_issue_run.status
    assert manual_issue_run.reviews_in_scope == cron_issue_run.reviews_in_scope
    assert manual_issue_run.reviews_succeeded == cron_issue_run.reviews_succeeded
