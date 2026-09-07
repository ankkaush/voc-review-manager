"""In-app notifications (§10). Deterministic side-effects of specific business events —
created at the exact call site that knows the context (issue detection, action
submitted for approval), not inferred generically from a workflow transition.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification

HIGH_PRIORITY_SEVERITIES = {"high"}


def create_notification(
    db: Session, business_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, message: str
) -> Notification:
    notification = Notification(
        business_id=business_id,
        entity_type=entity_type,
        entity_id=str(entity_id),
        message=message,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def notify_new_high_priority_issue(db: Session, issue) -> Notification | None:
    """Called after recurring-issue detection computes severity for a newly-created
    issue. Only high-severity NEW issues notify — recurring detection runs frequently
    and re-attaches evidence to existing issues constantly; that's not new information.
    """
    if issue.severity not in HIGH_PRIORITY_SEVERITIES:
        return None
    return create_notification(
        db,
        business_id=issue.business_id,
        entity_type="issue",
        entity_id=issue.id,
        message=f"New high-priority issue identified: {issue.title}",
    )


def notify_action_pending_approval(db: Session, action, issue) -> Notification:
    return create_notification(
        db,
        business_id=issue.business_id,
        entity_type="action",
        entity_id=action.id,
        message=f"Action awaiting approval: {issue.title}",
    )


def list_notifications(db: Session, business_id: uuid.UUID, unread_only: bool = False) -> list[Notification]:
    query = select(Notification).where(Notification.business_id == business_id)
    if unread_only:
        query = query.where(Notification.read.is_(False))
    query = query.order_by(Notification.created_at.desc())
    return list(db.execute(query).scalars().all())


def mark_notification_read(db: Session, notification: Notification) -> Notification:
    notification.read = True
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification
