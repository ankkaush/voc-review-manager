import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI-derived, per-review interpretation (§3). One row per Review — the 1:1
    relationship is enforced by the unique constraint on review_id.

    `ai_invocation_id` is the provenance link (§5): every field here traces back to a
    specific logged Claude call, model, and prompt version — never an unattributed claim.
    """

    __tablename__ = "review_analyses"
    __table_args__ = (UniqueConstraint("review_id", name="uq_review_analysis_review_id"),)

    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id"), nullable=False, index=True)
    ai_invocation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_invocations.id"), nullable=False)

    overall_sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")


class ReviewAspect(UUIDPrimaryKeyMixin, Base):
    """The atomic unit all later aggregation/issue-detection is built on (§3). One review
    can produce several of these (multi-aspect reviews).
    """

    __tablename__ = "review_aspects"

    review_analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_analyses.id"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    aspect_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aspects.id"), nullable=False, index=True)

    aspect_sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_snippet: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
