"""Ingestion core logic (§11: `ingestion` module owns `Review`).

Shared by both POST /reviews and POST /reviews/batch so the two endpoints can never
drift on validation/dedup/idempotency behavior. Deliberately structured around
per-item try/except and per-item commits (§8 reliability model: one bad review must
never crash or roll back the rest of a batch).
"""

import hashlib
import logging
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.language import detect_language
from app.ingestion.schemas import BatchIngestResponse, ReviewIn, ReviewIngestResult
from app.models.business import Business
from app.models.location import Location
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)
from app.models.review import AnalysisStatus, IngestionStatus, Review

logger = logging.getLogger(__name__)


def compute_content_hash(location_id: str, text: str) -> str:
    normalized = text.strip().lower()
    return hashlib.sha256(f"{location_id}:{normalized}".encode()).hexdigest()


def _find_duplicate(db: Session, review_in: ReviewIn, content_hash: str) -> Review | None:
    """Two independent dedup paths, matching the two unique constraints on Review (§3):

    - A review with a `source_review_id` is deduped against that id only. Sharing
      wording with another review at the same location is expected and NOT a duplicate.
    - A review with no `source_review_id` (no stable external id) falls back to
      content-hash dedup, since that id-less case is exactly what that constraint exists
      for.
    """
    if review_in.source_review_id:
        return db.execute(
            select(Review).where(
                Review.business_id == review_in.business_id,
                Review.source == review_in.source,
                Review.source_review_id == review_in.source_review_id,
            )
        ).scalar_one_or_none()

    return db.execute(
        select(Review).where(
            Review.business_id == review_in.business_id,
            Review.location_id == review_in.location_id,
            Review.content_hash == content_hash,
            Review.source_review_id.is_(None),
        )
    ).scalar_one_or_none()


def ingest_single_item(db: Session, raw_item: dict, index: int) -> ReviewIngestResult:
    """Validates, dedupes, and persists one review. Never raises for expected outcomes
    (validation failure, duplicate, unknown business/location) — those are all
    first-class results, not exceptions. Commits its own transaction on success so a
    later item's failure can't roll this one back.
    """
    try:
        review_in = ReviewIn.model_validate(raw_item)
    except ValidationError as exc:
        return ReviewIngestResult(index=index, ingestion_status="rejected", error=exc.errors()[0]["msg"])

    business = db.get(Business, review_in.business_id)
    if business is None:
        return ReviewIngestResult(index=index, ingestion_status="rejected", error="Unknown business_id")

    location = db.get(Location, review_in.location_id)
    if location is None or location.business_id != review_in.business_id:
        return ReviewIngestResult(
            index=index, ingestion_status="rejected", error="location_id does not belong to business_id"
        )

    content_hash = compute_content_hash(str(review_in.location_id), review_in.text)

    existing = _find_duplicate(db, review_in, content_hash)
    if existing is not None:
        return ReviewIngestResult(index=index, ingestion_status="duplicate", review_id=existing.id)

    detected_language = detect_language(review_in.text)

    review = Review(
        business_id=review_in.business_id,
        location_id=review_in.location_id,
        source=review_in.source,
        source_review_id=review_in.source_review_id,
        content_hash=content_hash,
        rating=review_in.rating,
        text=review_in.text,
        detected_language=detected_language,
        reviewer_display_name=review_in.reviewer_display_name,
        submitted_at=review_in.submitted_at,
        ingestion_status=IngestionStatus.ACCEPTED,
        analysis_status=AnalysisStatus.PENDING,
    )

    try:
        db.add(review)
        db.commit()
    except Exception:
        db.rollback()
        # Safety net for a race between the pre-check above and this insert; the unique
        # constraints are the real guarantee, this just turns a rare race into a clean
        # "duplicate" result instead of a 500.
        existing = _find_duplicate(db, review_in, content_hash)
        if existing is not None:
            return ReviewIngestResult(index=index, ingestion_status="duplicate", review_id=existing.id)
        logger.exception("Unexpected error persisting review", extra={"context": {"index": index}})
        return ReviewIngestResult(
            index=index, ingestion_status="rejected", error="Unexpected persistence error"
        )

    db.refresh(review)
    return ReviewIngestResult(
        index=index, ingestion_status="accepted", review_id=review.id, detected_language=detected_language
    )


def ingest_batch(
    db: Session, raw_items: list[dict], trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL
) -> BatchIngestResponse:
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.INGEST,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
        reviews_in_scope=len(raw_items),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    results: list[ReviewIngestResult] = []
    accepted = duplicate = rejected = 0

    for index, raw_item in enumerate(raw_items):
        result = ingest_single_item(db, raw_item, index)
        results.append(result)
        if result.ingestion_status == "accepted":
            accepted += 1
        elif result.ingestion_status == "duplicate":
            duplicate += 1
        else:
            rejected += 1

    run.finished_at = datetime.now(UTC)
    run.reviews_succeeded = accepted
    run.reviews_failed = rejected
    run.status = ProcessingRunStatus.COMPLETED_WITH_ERRORS if rejected else ProcessingRunStatus.COMPLETED
    db.commit()

    return BatchIngestResponse(
        processing_run_id=run.id,
        total=len(raw_items),
        accepted=accepted,
        duplicate=duplicate,
        rejected=rejected,
        results=results,
    )
