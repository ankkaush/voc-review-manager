import enum
import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OutcomeInterpretation(str, enum.Enum):
    IMPROVED = "improved"
    WORSENED = "worsened"
    NO_SIGNIFICANT_CHANGE = "no_significant_change"
    INSUFFICIENT_DATA = "insufficient_data"


class Outcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Deterministic before/after comparison for a resolved Action (§3): "did the
    business response actually work" as a re-derivable metric, never an unsupported
    claim. One row per action, upserted in place on re-evaluation (§11: `actions` owns
    `Outcome`).

    Deliberately stores computed period/count summaries rather than FK-ing a single
    `AggregatePeriodMetric` row per side (§3 allows normalizing/denormalizing as
    appropriate) — "before"/"after" are each a multi-week window sum, matching how
    trend detection (Phase 5) already works, not one arbitrary week.
    """

    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("action_id", name="uq_outcome_action_id"),)

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), nullable=False, index=True)

    before_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    before_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    before_negative_count: Mapped[int] = mapped_column(Integer, nullable=False)

    after_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    after_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    after_negative_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    interpretation: Mapped[OutcomeInterpretation] = mapped_column(String(32), nullable=False)
