import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AggregatePeriodMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fully deterministic weekly rollup (§3, §11) — computed from ReviewAspect by the
    `aggregation` module, never hand-edited, never AI-touched. This is the provenance
    backbone every trend/issue claim traces back to (§5).

    `location_id = NULL` means a business-wide rollup across all locations, distinct
    from any single location's row — enforced by the partial unique index below since a
    plain multi-column unique constraint treats every NULL as distinct in Postgres.
    """

    __tablename__ = "aggregate_period_metrics"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "location_id", "topic_id", "aspect_id", "period_start",
            name="uq_apm_scope_period",
        ),
        Index(
            "uq_apm_scope_period_business_wide",
            "business_id", "topic_id", "aspect_id", "period_start",
            unique=True,
            postgresql_where=text("location_id IS NULL"),
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    aspect_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aspects.id"), nullable=False, index=True)

    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
