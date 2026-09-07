import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Topic(UUIDPrimaryKeyMixin, Base):
    """Controlled vocabulary for classification (§3) — static/seed data, not user-editable
    in v1. Gives Phase 3's AI classification a fixed set of labels to choose from instead
    of free-form invented categories, which is what makes deterministic aggregation
    (Phase 4) possible at all.
    """

    __tablename__ = "topics"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)


class Aspect(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "aspects"
    __table_args__ = (UniqueConstraint("topic_id", "key", name="uq_aspect_topic_key"),)

    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
