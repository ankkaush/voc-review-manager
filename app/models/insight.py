import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GenerationMethod(str, enum.Enum):
    DETERMINISTIC_TEMPLATE = "deterministic_template"
    LLM_SYNTHESIS = "llm_synthesis"


class Insight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The human-readable narrative for an Issue (§3) — always generated *from* its
    IssueEvidence/trend snapshot, never independently. Multiple rows can exist per
    issue over time (re-generated as evidence changes); the latest by `created_at` is
    the current one.

    `ai_invocation_id` is null only for a deterministic-template fallback (e.g. when no
    API key is configured) — otherwise it links to the exact grounded Claude call that
    produced this text (§5 provenance).
    """

    __tablename__ = "insights"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(1000), nullable=False)
    generation_method: Mapped[GenerationMethod] = mapped_column(String(32), nullable=False)
    ai_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id"), nullable=True
    )
