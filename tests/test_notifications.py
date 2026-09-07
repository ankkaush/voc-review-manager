"""Notification tests (Phase 10): deterministic side-effects of specific business
events, not AI-generated. No mocks needed — everything here is deterministic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.service import recommend_action, submit_action_for_approval
from app.aggregation.service import compute_weekly_aggregates, week_start
from app.config import get_settings
from app.issues.service import detect_recurring_issues, review_issue
from app.models.issue import Issue
from app.models.notification import Notification
from app.notifications.service import list_notifications, mark_notification_read
from tests.factories import create_analyzed_review, create_business_and_location

settings = get_settings()
_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=70)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


@pytest.mark.integration
def test_new_high_severity_issue_creates_notification(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    notifications = list_notifications(db_session, business.id)
    assert len(notifications) == 1
    assert "Wait Time" in notifications[0].message
    assert notifications[0].entity_type == "issue"
    assert notifications[0].read is False


@pytest.mark.integration
def test_low_severity_issue_does_not_notify(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="low", rating=1, text=f"Bit slow, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    assert list_notifications(db_session, business.id) == []


@pytest.mark.integration
def test_rerunning_detection_does_not_duplicate_notification(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)
    detect_recurring_issues(db_session, business.id)  # re-run, e.g. a later scheduled pass

    assert len(list_notifications(db_session, business.id)) == 1


@pytest.mark.integration
def test_action_submitted_for_approval_creates_notification(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    issue = db_session.execute(select(Issue).where(Issue.business_id == business.id)).scalar_one()
    review_issue(db_session, issue, actor="manager@example.com")
    settings_no_key = settings.model_copy(update={"anthropic_api_key": None})
    action = recommend_action(db_session, issue, settings_no_key, actor="manager@example.com")

    before_count = len(list_notifications(db_session, business.id))
    submit_action_for_approval(db_session, action, actor="manager@example.com")
    after = list_notifications(db_session, business.id)

    assert len(after) == before_count + 1
    approval_notifications = [n for n in after if n.entity_type == "action"]
    assert len(approval_notifications) == 1
    assert "awaiting approval" in approval_notifications[0].message.lower()


@pytest.mark.unit
def test_mark_notification_read(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    for week_offset, count in enumerate([3, 3, 3, 3, 5, 7, 9, 18]):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    notification = list_notifications(db_session, business.id)[0]
    assert notification.read is False

    updated = mark_notification_read(db_session, notification)
    assert updated.read is True
    assert updated.read_at is not None

    unread = list_notifications(db_session, business.id, unread_only=True)
    assert unread == []


@pytest.mark.unit
def test_notification_model_stored_correctly(db_session: Session) -> None:
    business, _location = create_business_and_location(db_session)
    import uuid

    from app.notifications.service import create_notification

    notification = create_notification(
        db_session, business_id=business.id, entity_type="issue", entity_id=uuid.uuid4(), message="Test"
    )
    stored = db_session.get(Notification, notification.id)
    assert stored is not None
    assert stored.message == "Test"
