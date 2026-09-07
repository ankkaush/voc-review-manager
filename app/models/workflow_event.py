from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only audit trail for every workflow state transition (§3, §H).

    Source-of-truth for "who did what, when" on Issue/Action/Review entities.
    Never mutated or deleted after insert; not derived from anything else.
    """

    __tablename__ = "workflow_events"

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    from_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)

    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
