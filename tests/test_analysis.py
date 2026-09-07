"""Unit/integration tests for the AI analysis pipeline (Phase 3).

The Claude client is mocked throughout — these tests verify the deterministic control
flow around it (validation, retry, dead-lettering, persistence, AIInvocation logging),
not Claude's actual classification quality. That's what `scripts/evaluate_ai_analysis.py`
(the AI quality eval, §6) is for, and it needs a real ANTHROPIC_API_KEY to run.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.claude_client import ClaudeToolResponse
from app.analysis.service import TaxonomyLookup, analyze_pending_reviews, analyze_review
from app.config import get_settings
from app.core.retry import TransientError
from app.models.ai_invocation import AIInvocation
from app.models.business import Business
from app.models.location import Location
from app.models.review import AnalysisStatus, IngestionStatus, Review, ReviewSource
from app.models.review_analysis import ReviewAnalysis, ReviewAspect

settings = get_settings()


@pytest.fixture()
def review(db_session: Session) -> Review:
    business = Business(name=f"Test Business {uuid.uuid4()}", industry="restaurant")
    db_session.add(business)
    db_session.flush()
    location = Location(business_id=business.id, name="Downtown", city="Springfield")
    db_session.add(location)
    db_session.flush()

    review = Review(
        business_id=business.id,
        location_id=location.id,
        source=ReviewSource.SEED,
        source_review_id=f"r-{uuid.uuid4()}",
        content_hash="irrelevant-for-this-test",
        rating=3,
        text="The food was great but we waited 45 minutes for a table.",
        submitted_at=datetime.now(UTC),
        ingestion_status=IngestionStatus.ACCEPTED,
        analysis_status=AnalysisStatus.PENDING,
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)
    return review


def _mock_response(raw_input: dict) -> ClaudeToolResponse:
    return ClaudeToolResponse(
        raw_input=raw_input,
        model="claude-haiku-4-5-20251001",
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=250,
    )


VALID_ANALYSIS = {
    "overall_sentiment": "mixed",
    "aspects": [
        {
            "topic_key": "food",
            "aspect_key": "food_quality",
            "aspect_sentiment": "positive",
            "evidence_snippet": "food was great",
        },
        {
            "topic_key": "service",
            "aspect_key": "wait_time",
            "aspect_sentiment": "negative",
            "evidence_snippet": "waited 45 minutes",
            "severity": "medium",
        },
    ],
}


@pytest.mark.integration
def test_analyze_review_success_persists_analysis_and_aspects(db_session: Session, review: Review) -> None:
    with patch("app.analysis.service.analyze_review_text", return_value=_mock_response(VALID_ANALYSIS)):
        status = analyze_review(db_session, review, settings, TaxonomyLookup(db_session))

    assert status == AnalysisStatus.ANALYZED
    db_session.refresh(review)
    assert review.analysis_status == AnalysisStatus.ANALYZED

    analysis = db_session.execute(
        select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
    ).scalar_one()
    assert analysis.overall_sentiment == "mixed"
    assert analysis.ai_invocation_id is not None

    aspects = db_session.execute(
        select(ReviewAspect).where(ReviewAspect.review_analysis_id == analysis.id)
    ).scalars().all()
    assert len(aspects) == 2

    invocation = db_session.get(AIInvocation, analysis.ai_invocation_id)
    assert invocation.validation_passed is True
    assert invocation.model == "claude-haiku-4-5-20251001"


@pytest.mark.integration
def test_analyze_review_invalid_taxonomy_pair_dead_letters_after_repair_attempt(
    db_session: Session, review: Review
) -> None:
    """Failure-injection test (§8 DoD): a persistently malformed structured output
    (here, a topic/aspect pair outside the seeded taxonomy) must dead-letter the review
    — not crash, not silently accept invalid data, not corrupt ReviewAnalysis.
    """
    invalid_response = _mock_response(
        {
            "overall_sentiment": "negative",
            "aspects": [
                {
                    "topic_key": "not_a_real_topic",
                    "aspect_key": "not_a_real_aspect",
                    "aspect_sentiment": "negative",
                    "evidence_snippet": "anything",
                }
            ],
        }
    )

    with patch("app.analysis.service.analyze_review_text", return_value=invalid_response):
        status = analyze_review(db_session, review, settings, TaxonomyLookup(db_session))

    assert status == AnalysisStatus.FAILED
    db_session.refresh(review)
    assert review.analysis_status == AnalysisStatus.FAILED

    # No ReviewAnalysis row was ever created for this review.
    existing = db_session.execute(
        select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
    ).scalar_one_or_none()
    assert existing is None

    # Both the original attempt and the one repair attempt were logged (§9: every call).
    invocations = db_session.execute(
        select(AIInvocation).where(AIInvocation.input_ref == str(review.id))
    ).scalars().all()
    assert len(invocations) == 2
    assert all(inv.validation_passed is False for inv in invocations)
    assert all(inv.error_type == "validation_error" for inv in invocations)


@pytest.mark.integration
def test_analyze_review_repair_succeeds_on_second_attempt(db_session: Session, review: Review) -> None:
    invalid_response = _mock_response({"overall_sentiment": "negative", "aspects": [{"topic_key": "bad"}]})
    valid_response = _mock_response(VALID_ANALYSIS)

    with patch(
        "app.analysis.service.analyze_review_text", side_effect=[invalid_response, valid_response]
    ):
        status = analyze_review(db_session, review, settings, TaxonomyLookup(db_session))

    assert status == AnalysisStatus.ANALYZED
    invocations = db_session.execute(
        select(AIInvocation).where(AIInvocation.input_ref == str(review.id))
    ).scalars().all()
    assert len(invocations) == 2
    assert invocations[0].validation_passed is False
    assert invocations[1].validation_passed is True


@pytest.mark.integration
def test_analyze_review_provider_error_marks_pending_retry_not_failed(
    db_session: Session, review: Review
) -> None:
    """§8: a transient provider failure must be retryable later, not a dead letter."""
    with patch("app.analysis.service.analyze_review_text", side_effect=TransientError("connection reset")):
        status = analyze_review(db_session, review, settings, TaxonomyLookup(db_session))

    assert status == AnalysisStatus.PENDING_RETRY
    db_session.refresh(review)
    assert review.analysis_status == AnalysisStatus.PENDING_RETRY

    invocation = db_session.execute(
        select(AIInvocation).where(AIInvocation.input_ref == str(review.id))
    ).scalar_one()
    assert invocation.error_type == "provider_error"
    assert invocation.validation_passed is False


@pytest.mark.unit
def test_analyze_pending_reviews_fails_fast_without_api_key(db_session: Session, review: Review) -> None:
    """A missing API key is a config problem, not a content problem — it must not
    dead-letter every pending review (§8).
    """
    settings_without_key = settings.model_copy(update={"anthropic_api_key": None})

    run = analyze_pending_reviews(db_session, settings_without_key, limit=10)

    assert run.status == "failed"
    assert run.reviews_in_scope == 0
    db_session.refresh(review)
    assert review.analysis_status == AnalysisStatus.PENDING  # untouched, not dead-lettered


@pytest.mark.integration
def test_analyze_pending_reviews_isolates_one_failure_from_the_rest(db_session: Session) -> None:
    """One review's failure must not stop the batch (§8 failure isolation)."""
    business = Business(name=f"Batch Test {uuid.uuid4()}", industry="restaurant")
    db_session.add(business)
    db_session.flush()
    location = Location(business_id=business.id, name="Uptown", city="Springfield")
    db_session.add(location)
    db_session.flush()

    reviews = []
    for i in range(3):
        r = Review(
            business_id=business.id,
            location_id=location.id,
            source=ReviewSource.SEED,
            source_review_id=f"batch-{i}-{uuid.uuid4()}",
            content_hash=f"hash-{i}",
            rating=3,
            text=f"Review number {i}, food was fine.",
            submitted_at=datetime.now(UTC),
            ingestion_status=IngestionStatus.ACCEPTED,
            analysis_status=AnalysisStatus.PENDING,
        )
        db_session.add(r)
        reviews.append(r)
    db_session.commit()

    responses = [
        _mock_response(VALID_ANALYSIS),
        TransientError("provider down"),
        _mock_response(VALID_ANALYSIS),
    ]

    def fake_analyze(text, settings, repair_error=None):
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    # analyze_pending_reviews fails fast without a configured key (§8: a config problem
    # shouldn't dead-letter every review) — the Claude call itself is mocked regardless.
    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})

    with patch("app.analysis.service.analyze_review_text", side_effect=fake_analyze):
        run = analyze_pending_reviews(db_session, settings_with_key, limit=10)

    assert run.reviews_in_scope == 3
    assert run.reviews_succeeded == 2
    assert run.reviews_failed == 0  # the transient one is pending_retry, not failed
    assert run.status == "completed"

    for r in reviews:
        db_session.refresh(r)
    statuses = sorted(r.analysis_status for r in reviews)
    expected = sorted([AnalysisStatus.ANALYZED, AnalysisStatus.ANALYZED, AnalysisStatus.PENDING_RETRY])
    assert statuses == expected
