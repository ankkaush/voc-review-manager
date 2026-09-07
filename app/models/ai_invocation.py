import enum
import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIOperation(str, enum.Enum):
    SENTIMENT_EXTRACTION = "sentiment_extraction"
    INSIGHT_SYNTHESIS = "insight_synthesis"
    ACTION_RECOMMENDATION = "action_recommendation"
    REVIEW_RESPONSE_DRAFT = "review_response_draft"


class AIInvocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """LLM observability (§9): every Claude call, no exceptions, is logged here.

    This table *is* the project's LLM observability system (ADR-4) — deliberately in
    place of Langfuse, since a small number of well-defined structured calls don't
    need a dedicated LLM tracing product.
    """

    __tablename__ = "ai_invocations"

    processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    operation: Mapped[AIOperation] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Loosely-typed reference (review id, issue id, ...) rather than a hard FK, since
    # this table logs calls made on behalf of several different entity types.
    input_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
