import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.issue import IssueStatus


class ActionType(str, enum.Enum):
    OPERATIONAL_TASK = "operational_task"
    PUBLIC_REVIEW_RESPONSE = "public_review_response"  # reserved; Phase 8 is optional/stretch


class Action(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed or approved business response to an Issue (§3). Shares Issue's status
    vocabulary (§workflow) — its own lifecycle from `recommended` through `resolved`,
    cascading the parent Issue's status as it progresses (§actions/service.py).
    """

    __tablename__ = "actions"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"), nullable=False, index=True)
    type: Mapped[ActionType] = mapped_column(String(32), nullable=False, default=ActionType.OPERATIONAL_TASK)
    recommended_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    ai_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id"), nullable=True
    )
    status: Mapped[IssueStatus] = mapped_column(String(32), nullable=False, default=IssueStatus.RECOMMENDED)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
