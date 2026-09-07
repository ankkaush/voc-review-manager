import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.notifications.schemas import NotificationOut
from app.notifications.service import list_notifications, mark_notification_read

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def get_notifications(
    business_id: uuid.UUID,
    unread_only: bool = False,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Notification]:
    return list_notifications(db, business_id, unread_only=unread_only)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return mark_notification_read(db, notification)
