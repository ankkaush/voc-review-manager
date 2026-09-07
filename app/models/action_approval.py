import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utcnow


class ApprovalDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class ActionApproval(UUIDPrimaryKeyMixin, Base):
    """A human decision on a recommended Action (§3) — kept separate from `Action`
    itself so an action's approval history stays auditable even if it's ever
    re-submitted. `modified_text` is set only when `decision=modified` (the approver
    edited the AI draft before approving it).
    """

    __tablename__ = "action_approvals"

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), nullable=False, index=True)
    decision: Mapped[ApprovalDecision] = mapped_column(String(16), nullable=False)
    approver: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    modified_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
