import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utcnow


class ReviewSource(str, enum.Enum):
    CSV = "csv"
    JSON = "json"
    SEED = "seed"
    MOCK_API = "mock_api"


class IngestionStatus(str, enum.Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class AnalysisStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    PENDING_RETRY = "pending_retry"
    FAILED = "failed"


class Review(UUIDPrimaryKeyMixin, Base):
    """Immutable source-of-truth input record (§3). Text/rating/metadata are never
    mutated after insert. Lifecycle is tracked via two independent status fields
    (ADR-10) because ingestion and AI analysis can fail independently of each other.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("business_id", "source", "source_review_id", name="uq_review_business_source_id"),
        # Content-hash idempotency applies ONLY when no external id was given (§3: "for
        # idempotency when no external id exists"). Without this WHERE clause, two
        # genuinely different reviews that happen to share wording at the same location
        # (common with short/templated feedback) would be impossible to both store even
        # though each carries its own distinct source_review_id.
        Index(
            "uq_review_business_location_hash_no_source_id",
            "business_id",
            "location_id",
            "content_hash",
            unique=True,
            postgresql_where=text("source_review_id IS NULL"),
        ),
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_review_rating_range"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)

    source: Mapped[ReviewSource] = mapped_column(String(16), nullable=False)
    source_review_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    rating: Mapped[int | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(String(5000), nullable=False)
    detected_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reviewer_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    ingestion_status: Mapped[IngestionStatus] = mapped_column(String(16), nullable=False)
    analysis_status: Mapped[AnalysisStatus | None] = mapped_column(String(16), nullable=True)
