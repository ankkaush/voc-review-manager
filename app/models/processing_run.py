import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProcessingRunTrigger(str, enum.Enum):
    CRON = "cron"
    MANUAL = "manual"


class ProcessingRunJobType(str, enum.Enum):
    INGEST = "ingest"
    ANALYZE = "analyze"
    AGGREGATE = "aggregate"
    ISSUE_DETECTION = "issue_detection"
    TREND = "trend"
    INSIGHT = "insight"
    OUTCOME = "outcome"
    SUMMARY = "summary"


class ProcessingRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ProcessingRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Technical observability: one row per pipeline run (§9 of ARCHITECTURE.md).

    Answers "what ran, when, how many succeeded/failed" independently of business
    analytics — never joined against or displayed on the customer-facing dashboard.
    """

    __tablename__ = "processing_runs"

    trigger: Mapped[ProcessingRunTrigger] = mapped_column(
        Enum(ProcessingRunTrigger, name="processing_run_trigger"), nullable=False
    )
    job_type: Mapped[ProcessingRunJobType] = mapped_column(
        Enum(ProcessingRunJobType, name="processing_run_job_type"), nullable=False
    )
    status: Mapped[ProcessingRunStatus] = mapped_column(
        Enum(ProcessingRunStatus, name="processing_run_status"),
        nullable=False,
        default=ProcessingRunStatus.RUNNING,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reviews_in_scope: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviews_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviews_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
