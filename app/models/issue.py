import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utcnow


class IssueStatus(str, enum.Enum):
    IDENTIFIED = "identified"
    REVIEWED = "reviewed"
    RECOMMENDED = "recommended"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTION_CREATED = "action_created"
    RESOLVED = "resolved"
    MONITORING = "monitoring"
    CLOSED = "closed"


class TrendDirection(str, enum.Enum):
    EMERGING = "emerging"
    DECLINING = "declining"
    STABLE = "stable"
    NEW = "new"  # no prior-period baseline to compare against yet
    INSUFFICIENT_DATA = "insufficient_data"


class Issue(UUIDPrimaryKeyMixin, Base):
    """A recurring pattern promoted to a trackable business problem (§3). Scoped to one
    (topic, aspect, location) combination — `location_id = NULL` would mean a
    business-wide issue, though v1 recurring-issue detection only promotes per-location
    issues (§E: keeps "which location is affected" concrete and actionable).

    `priority_score`/`priority_score_breakdown` are populated in Phase 5 — present now
    because they're part of the approved Phase 0 domain model, but always NULL until
    then.
    """

    __tablename__ = "issues"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    aspect_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aspects.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[IssueStatus] = mapped_column(String(32), nullable=False, default=IssueStatus.IDENTIFIED)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)

    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_score_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    trend_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trend_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class EvidenceType(str, enum.Enum):
    METRIC = "metric"
    REVIEW_CITATION = "review_citation"


class IssueEvidence(UUIDPrimaryKeyMixin, Base):
    """The provenance join (§5): lets the dashboard walk Issue -> IssueEvidence ->
    either an AggregatePeriodMetric (the numbers behind a claim) or a specific Review
    (a representative citation) — never an unsupported claim.
    """

    __tablename__ = "issue_evidence"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"), nullable=False, index=True)
    aggregate_period_metric_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("aggregate_period_metrics.id"), nullable=True, index=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reviews.id"), nullable=True, index=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
