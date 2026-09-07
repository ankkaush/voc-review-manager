"""Business analytics read-model (§9 mentor point 8): pure read queries over existing
tables, no new persisted state. Deliberately kept separate from `/system-health`
(technical observability) per the architecture's business-vs-technical split.
"""

import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.schemas import AspectsResponse, AspectSummary, OverviewResponse
from app.models.review import Review
from app.models.review_analysis import ReviewAnalysis, ReviewAspect
from app.models.taxonomy import Aspect, Topic

TOP_ASPECTS_LIMIT = 10


def get_overview(db: Session, business_id: uuid.UUID) -> OverviewResponse:
    reviews = db.execute(select(Review).where(Review.business_id == business_id)).scalars().all()

    ingestion_status_counts = Counter(r.ingestion_status for r in reviews)
    analysis_status_counts = Counter(r.analysis_status for r in reviews if r.analysis_status is not None)
    rating_distribution = Counter(str(r.rating) for r in reviews if r.rating is not None)
    language_distribution = Counter(r.detected_language for r in reviews if r.detected_language)

    sentiment_rows = db.execute(
        select(ReviewAnalysis.overall_sentiment)
        .join(Review, Review.id == ReviewAnalysis.review_id)
        .where(Review.business_id == business_id)
    ).all()
    sentiment_distribution = Counter(s for (s,) in sentiment_rows)

    return OverviewResponse(
        business_id=business_id,
        review_count=len(reviews),
        ingestion_status_counts=dict(ingestion_status_counts),
        analysis_status_counts=dict(analysis_status_counts),
        rating_distribution=dict(rating_distribution),
        sentiment_distribution=dict(sentiment_distribution),
        language_distribution=dict(language_distribution),
    )


def get_top_aspects(db: Session, business_id: uuid.UUID, limit: int = TOP_ASPECTS_LIMIT) -> AspectsResponse:
    rows = db.execute(
        select(
            Topic.key, Topic.label, Aspect.key, Aspect.label, ReviewAspect.aspect_sentiment,
        )
        .select_from(ReviewAspect)
        .join(ReviewAnalysis, ReviewAnalysis.id == ReviewAspect.review_analysis_id)
        .join(Review, Review.id == ReviewAnalysis.review_id)
        .join(Topic, Topic.id == ReviewAspect.topic_id)
        .join(Aspect, Aspect.id == ReviewAspect.aspect_id)
        .where(Review.business_id == business_id)
    ).all()

    summaries: dict[tuple[str, str], dict] = {}
    for topic_key, topic_label, aspect_key, aspect_label, sentiment in rows:
        key = (topic_key, aspect_key)
        entry = summaries.setdefault(
            key,
            {
                "topic_key": topic_key, "topic_label": topic_label,
                "aspect_key": aspect_key, "aspect_label": aspect_label,
                "mention_count": 0, "negative_count": 0, "positive_count": 0,
            },
        )
        entry["mention_count"] += 1
        if sentiment == "negative":
            entry["negative_count"] += 1
        elif sentiment == "positive":
            entry["positive_count"] += 1

    all_summaries = [AspectSummary(**entry) for entry in summaries.values()]
    top_negative = sorted(all_summaries, key=lambda s: s.negative_count, reverse=True)[:limit]
    top_negative = [s for s in top_negative if s.negative_count > 0]
    top_positive = sorted(all_summaries, key=lambda s: s.positive_count, reverse=True)[:limit]
    top_positive = [s for s in top_positive if s.positive_count > 0]

    return AspectsResponse(top_negative=top_negative, top_positive=top_positive)
