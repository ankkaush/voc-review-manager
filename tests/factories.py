"""Shared test fixtures for creating fully-analyzed reviews without a real Claude call.

Phase 4+ tests build directly on ReviewAspect data (the output of Phase 3's AI layer)
to test aggregation/issue-detection logic in isolation — exactly like Phase 3's own
tests mocked the Claude client to isolate its control flow. Neither needs a live API key.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_invocation import AIInvocation, AIOperation
from app.models.business import Business
from app.models.location import Location
from app.models.review import AnalysisStatus, IngestionStatus, Review, ReviewSource
from app.models.review_analysis import ReviewAnalysis, ReviewAspect
from app.models.taxonomy import Aspect, Topic


def create_business_and_location(db: Session, name_prefix: str = "Test") -> tuple[Business, Location]:
    business = Business(name=f"{name_prefix} Business {uuid.uuid4()}", industry="restaurant")
    db.add(business)
    db.flush()
    location = Location(
        business_id=business.id, name=f"{name_prefix} Location {uuid.uuid4()}", city="Springfield"
    )
    db.add(location)
    db.flush()
    return business, location


def resolve_topic_aspect(db: Session, topic_key: str, aspect_key: str) -> tuple[uuid.UUID, uuid.UUID]:
    topic = db.execute(select(Topic).where(Topic.key == topic_key)).scalar_one()
    aspect = db.execute(
        select(Aspect).where(Aspect.topic_id == topic.id, Aspect.key == aspect_key)
    ).scalar_one()
    return topic.id, aspect.id


def create_analyzed_review(
    db: Session,
    business: Business,
    location: Location,
    *,
    submitted_at: datetime,
    topic_key: str,
    aspect_key: str,
    aspect_sentiment: str,
    overall_sentiment: str | None = None,
    severity: str | None = None,
    rating: int | None = 3,
    text: str = "Fixture review text",
) -> Review:
    """Creates a Review + ReviewAnalysis + ReviewAspect + AIInvocation chain as if Phase
    3's pipeline had already successfully analyzed it — bypassing the real Claude call.
    """
    review = Review(
        business_id=business.id,
        location_id=location.id,
        source=ReviewSource.SEED,
        source_review_id=f"fx-{uuid.uuid4()}",
        content_hash=f"fx-hash-{uuid.uuid4()}",
        rating=rating,
        text=text,
        submitted_at=submitted_at,
        ingestion_status=IngestionStatus.ACCEPTED,
        analysis_status=AnalysisStatus.ANALYZED,
    )
    db.add(review)
    db.flush()

    invocation = AIInvocation(
        operation=AIOperation.SENTIMENT_EXTRACTION,
        model="test-fixture",
        prompt_version="v1",
        validation_passed=True,
        input_ref=str(review.id),
    )
    db.add(invocation)
    db.flush()

    analysis = ReviewAnalysis(
        review_id=review.id,
        ai_invocation_id=invocation.id,
        overall_sentiment=overall_sentiment or aspect_sentiment,
        model="test-fixture",
        prompt_version="v1",
    )
    db.add(analysis)
    db.flush()

    topic_id, aspect_id = resolve_topic_aspect(db, topic_key, aspect_key)
    db.add(
        ReviewAspect(
            review_analysis_id=analysis.id,
            topic_id=topic_id,
            aspect_id=aspect_id,
            aspect_sentiment=aspect_sentiment,
            evidence_snippet=text[:50],
            severity=severity,
        )
    )
    db.commit()
    return review
