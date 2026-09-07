"""Deterministic weekly rollups (§11: `aggregation` module owns `AggregatePeriodMetric`).

Pure Python/SQL computation, no AI calls, fully unit-testable in isolation from the
analysis pipeline that produces its input (`ReviewAspect`). Every run recomputes from
scratch and upserts by natural key, so already-referenced metric rows (via
`IssueEvidence`) keep stable ids across re-runs — this is what "regenerable" (§3) means
in practice, not "delete and reinsert."
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)
from app.models.review import Review
from app.models.review_analysis import ReviewAnalysis, ReviewAspect


def week_start(dt: datetime | date) -> date:
    """Monday-aligned calendar week — an explainable, standard bucketing scheme,
    independent of any dataset-specific week numbering (§7's generator has its own
    internal week index; this must work on any real timestamp, not just synthetic data).
    """
    d = dt.date() if isinstance(dt, datetime) else dt
    return d - timedelta(days=d.weekday())


@dataclass
class _Bucket:
    mention_count: int = 0
    negative_count: int = 0
    positive_count: int = 0
    neutral_count: int = 0
    rating_sum: float = 0.0
    rating_count: int = 0

    def add(self, sentiment: str, rating: int | None) -> None:
        self.mention_count += 1
        if sentiment == "negative":
            self.negative_count += 1
        elif sentiment == "positive":
            self.positive_count += 1
        else:
            self.neutral_count += 1
        if rating is not None:
            self.rating_sum += rating
            self.rating_count += 1

    @property
    def avg_rating(self) -> float | None:
        return self.rating_sum / self.rating_count if self.rating_count else None


def _location_filter(location_id: uuid.UUID | None):
    if location_id is None:
        return AggregatePeriodMetric.location_id.is_(None)
    return AggregatePeriodMetric.location_id == location_id


def _upsert_metric(
    db: Session,
    business_id: uuid.UUID,
    location_id: uuid.UUID | None,
    topic_id: uuid.UUID,
    aspect_id: uuid.UUID,
    period_start: date,
    bucket: _Bucket,
) -> AggregatePeriodMetric:
    existing = db.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business_id,
            _location_filter(location_id),
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
            AggregatePeriodMetric.period_start == period_start,
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = AggregatePeriodMetric(
            business_id=business_id,
            location_id=location_id,
            topic_id=topic_id,
            aspect_id=aspect_id,
            period_start=period_start,
            period_end=period_start + timedelta(days=6),
        )
        db.add(existing)

    existing.period_end = period_start + timedelta(days=6)
    existing.mention_count = bucket.mention_count
    existing.negative_count = bucket.negative_count
    existing.positive_count = bucket.positive_count
    existing.neutral_count = bucket.neutral_count
    existing.avg_rating = bucket.avg_rating
    return existing


def compute_weekly_aggregates(
    db: Session, business_id: uuid.UUID, trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL
) -> ProcessingRun:
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.AGGREGATE,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    rows = db.execute(
        select(
            Review.location_id,
            Review.rating,
            Review.submitted_at,
            ReviewAspect.topic_id,
            ReviewAspect.aspect_id,
            ReviewAspect.aspect_sentiment,
        )
        .select_from(Review)
        .join(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .join(ReviewAspect, ReviewAspect.review_analysis_id == ReviewAnalysis.id)
        .where(Review.business_id == business_id)
    ).all()

    per_location: dict[tuple, _Bucket] = defaultdict(_Bucket)
    per_business: dict[tuple, _Bucket] = defaultdict(_Bucket)

    for location_id, rating, submitted_at, topic_id, aspect_id, sentiment in rows:
        period = week_start(submitted_at)
        per_location[(location_id, topic_id, aspect_id, period)].add(sentiment, rating)
        per_business[(topic_id, aspect_id, period)].add(sentiment, rating)

    for (location_id, topic_id, aspect_id, period), bucket in per_location.items():
        _upsert_metric(db, business_id, location_id, topic_id, aspect_id, period, bucket)

    for (topic_id, aspect_id, period), bucket in per_business.items():
        _upsert_metric(db, business_id, None, topic_id, aspect_id, period, bucket)

    analyzed_review_count = len(
        db.execute(
            select(ReviewAnalysis.id)
            .join(Review, Review.id == ReviewAnalysis.review_id)
            .where(Review.business_id == business_id)
        ).all()
    )

    run.finished_at = datetime.now(UTC)
    run.reviews_in_scope = analyzed_review_count
    run.reviews_succeeded = analyzed_review_count
    run.reviews_failed = 0
    run.status = ProcessingRunStatus.COMPLETED
    db.commit()

    return run
