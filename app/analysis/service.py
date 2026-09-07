"""Per-review AI analysis orchestration (§8 reliability model, §D responsibility split).

AI (via `claude_client`) does the interpretation. Everything here — retry policy,
validation, persistence, status transitions, dead-lettering, AIInvocation logging — is
deterministic control flow. One review's failure never raises past this module; the
caller (a batch job) can loop over many reviews without per-item try/except of its own.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.claude_client import ClaudeToolResponse, analyze_review_text
from app.analysis.schemas import ReviewAnalysisResult
from app.config import Settings
from app.core.retry import TransientError
from app.models.ai_invocation import AIInvocation, AIOperation
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)
from app.models.review import AnalysisStatus, Review
from app.models.review_analysis import ReviewAnalysis, ReviewAspect
from app.models.taxonomy import Aspect, Topic

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


class TaxonomyLookup:
    """Preloaded topic/aspect key -> id map, built once per batch run instead of
    querying per aspect per review.
    """

    def __init__(self, db: Session):
        topics = db.execute(select(Topic)).scalars().all()
        aspects = db.execute(select(Aspect)).scalars().all()

        topic_id_by_key = {t.key: t.id for t in topics}
        topic_key_by_id = {t.id: t.key for t in topics}

        self._ids_by_pair: dict[tuple[str, str], tuple[uuid.UUID, uuid.UUID]] = {
            (topic_key_by_id[a.topic_id], a.key): (a.topic_id, a.id) for a in aspects
        }
        self._topic_ids_by_key = topic_id_by_key

    def resolve(self, topic_key: str, aspect_key: str) -> tuple[uuid.UUID, uuid.UUID]:
        return self._ids_by_pair[(topic_key, aspect_key)]


@dataclass
class _AttemptOutcome:
    result: ReviewAnalysisResult | None
    invocation: AIInvocation
    error_message: str | None


def _log_invocation(
    db: Session,
    review: Review,
    settings: Settings,
    processing_run_id: uuid.UUID | None,
    *,
    latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    validation_passed: bool,
    error_type: str | None,
) -> AIInvocation:
    invocation = AIInvocation(
        processing_run_id=processing_run_id,
        operation=AIOperation.SENTIMENT_EXTRACTION,
        model=settings.analysis_model,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        # Not fabricated: per-token pricing for the configured model isn't hardcoded
        # here, so cost stays honestly unset rather than an invented estimate.
        cost_estimate_usd=None,
        validation_passed=validation_passed,
        error_type=error_type,
        input_ref=str(review.id),
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)
    return invocation


def _attempt_and_validate(
    db: Session,
    review: Review,
    settings: Settings,
    processing_run_id: uuid.UUID | None,
    repair_error: str | None = None,
) -> _AttemptOutcome:
    """Makes exactly one Claude call and validates it, logging exactly one AIInvocation
    row regardless of outcome (§9: every AI call is logged, no exceptions).
    """
    try:
        response: ClaudeToolResponse = analyze_review_text(
            review.text, settings, repair_error=repair_error
        )
    except TransientError as exc:
        invocation = _log_invocation(
            db, review, settings, processing_run_id,
            latency_ms=None, prompt_tokens=None, completion_tokens=None,
            validation_passed=False, error_type="provider_error",
        )
        logger.warning(
            "Analysis provider error", extra={"context": {"review_id": str(review.id), "error": str(exc)}}
        )
        return _AttemptOutcome(result=None, invocation=invocation, error_message=str(exc))

    try:
        result = ReviewAnalysisResult.model_validate(response.raw_input)
    except ValidationError as exc:
        invocation = _log_invocation(
            db, review, settings, processing_run_id,
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            validation_passed=False, error_type="validation_error",
        )
        return _AttemptOutcome(result=None, invocation=invocation, error_message=str(exc))

    invocation = _log_invocation(
        db, review, settings, processing_run_id,
        latency_ms=response.latency_ms,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        validation_passed=True, error_type=None,
    )
    return _AttemptOutcome(result=result, invocation=invocation, error_message=None)


def _check_evidence_groundedness(review: Review, result: ReviewAnalysisResult) -> None:
    """Secondary, non-blocking safety net (§5/ADR-11) — logs a warning if an aspect's
    evidence snippet isn't actually found in the source text. Never blocks persistence:
    the deterministic fields (topic/aspect/sentiment) are still trustworthy on their own.
    """
    lowered_text = review.text.lower()
    for aspect in result.aspects:
        if aspect.evidence_snippet.lower() not in lowered_text:
            logger.warning(
                "Evidence snippet not found verbatim in review text",
                extra={"context": {"review_id": str(review.id), "snippet": aspect.evidence_snippet}},
            )


def _persist_analysis(
    db: Session,
    review: Review,
    result: ReviewAnalysisResult,
    invocation: AIInvocation,
    taxonomy: TaxonomyLookup,
) -> None:
    analysis = ReviewAnalysis(
        review_id=review.id,
        ai_invocation_id=invocation.id,
        overall_sentiment=result.overall_sentiment,
        model=invocation.model,
        prompt_version=PROMPT_VERSION,
    )
    db.add(analysis)
    db.flush()

    for aspect_result in result.aspects:
        topic_id, aspect_id = taxonomy.resolve(aspect_result.topic_key, aspect_result.aspect_key)
        db.add(
            ReviewAspect(
                review_analysis_id=analysis.id,
                topic_id=topic_id,
                aspect_id=aspect_id,
                aspect_sentiment=aspect_result.aspect_sentiment,
                evidence_snippet=aspect_result.evidence_snippet,
                severity=aspect_result.severity,
            )
        )


def analyze_review(
    db: Session,
    review: Review,
    settings: Settings,
    taxonomy: TaxonomyLookup,
    processing_run_id: uuid.UUID | None = None,
) -> AnalysisStatus:
    """Analyzes one review end to end. Never raises — every outcome (success, dead
    letter, retry-later) is reflected in the review's `analysis_status` and returned.
    """
    review.analysis_status = AnalysisStatus.PROCESSING
    db.commit()

    outcome = _attempt_and_validate(db, review, settings, processing_run_id)

    if outcome.result is None and outcome.invocation.error_type == "provider_error":
        review.analysis_status = AnalysisStatus.PENDING_RETRY
        db.commit()
        return AnalysisStatus.PENDING_RETRY

    if outcome.result is None:
        # One repair attempt: re-prompt with the validation error appended (§8).
        repair_outcome = _attempt_and_validate(
            db, review, settings, processing_run_id, repair_error=outcome.error_message
        )
        if repair_outcome.result is None:
            status = (
                AnalysisStatus.PENDING_RETRY
                if repair_outcome.invocation.error_type == "provider_error"
                else AnalysisStatus.FAILED
            )
            review.analysis_status = status
            db.commit()
            return status
        outcome = repair_outcome

    _check_evidence_groundedness(review, outcome.result)
    _persist_analysis(db, review, outcome.result, outcome.invocation, taxonomy)
    review.analysis_status = AnalysisStatus.ANALYZED
    db.commit()
    return AnalysisStatus.ANALYZED


def analyze_pending_reviews(
    db: Session,
    settings: Settings,
    limit: int = 100,
    trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL,
) -> ProcessingRun:
    """Batch entry point (§2: database-backed pending work, not a queue). Picks up
    every review with analysis_status pending/pending_retry, up to `limit`, and
    processes each independently — one failure never stops the batch.
    """
    if not settings.anthropic_api_key:
        # Fail fast at the run level rather than looping through every pending review
        # and dead-lettering each one for what is a configuration problem, not a
        # content problem — those are different failure classes (§8).
        run = ProcessingRun(
            trigger=trigger,
            job_type=ProcessingRunJobType.ANALYZE,
            status=ProcessingRunStatus.FAILED,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            reviews_in_scope=0,
            error_summary="ANTHROPIC_API_KEY is not configured",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    pending = (
        db.execute(
            select(Review)
            .where(Review.analysis_status.in_([AnalysisStatus.PENDING, AnalysisStatus.PENDING_RETRY]))
            .limit(limit)
        )
        .scalars()
        .all()
    )

    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.ANALYZE,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
        reviews_in_scope=len(pending),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    taxonomy = TaxonomyLookup(db)
    succeeded = failed = 0

    for review in pending:
        try:
            status = analyze_review(db, review, settings, taxonomy, processing_run_id=run.id)
        except Exception:
            db.rollback()
            review.analysis_status = AnalysisStatus.FAILED
            db.commit()
            logger.exception(
                "Unexpected error analyzing review", extra={"context": {"review_id": str(review.id)}}
            )
            status = AnalysisStatus.FAILED

        if status == AnalysisStatus.ANALYZED:
            succeeded += 1
        elif status == AnalysisStatus.FAILED:
            failed += 1
        # PENDING_RETRY is neither a success nor a failure for this run's tally — it
        # will be picked up again by a later run.

    run.finished_at = datetime.now(UTC)
    run.reviews_succeeded = succeeded
    run.reviews_failed = failed
    run.status = ProcessingRunStatus.COMPLETED_WITH_ERRORS if failed else ProcessingRunStatus.COMPLETED
    db.commit()

    return run
