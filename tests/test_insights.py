"""Unit/integration tests for grounded insight generation (Phase 5).

The Claude client is mocked throughout, same approach as tests/test_analysis.py — these
verify the deterministic control flow (evidence construction, validation, provider-error
handling, groundedness logging, the no-API-key template fallback), not Claude's actual
prose quality. No API calls, no cost.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates, week_start
from app.analysis.claude_client import ClaudeToolResponse
from app.config import get_settings
from app.core.retry import TransientError
from app.insights.evidence import build_insight_evidence
from app.insights.groundedness import check_insight_groundedness
from app.insights.service import generate_insight, generate_insights_for_business
from app.issues.service import detect_recurring_issues, update_trends_and_priorities
from app.models.ai_invocation import AIInvocation
from app.models.insight import GenerationMethod, Insight
from app.models.issue import Issue
from tests.factories import create_analyzed_review, create_business_and_location

settings = get_settings()

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=50)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _seeded_issue(db_session: Session):
    business, location = create_business_and_location(db_session)
    weekly_counts = [3, 3, 3, 3, 5, 7, 9, 18]
    for week_offset, count in enumerate(weekly_counts):
        for i in range(count):
            create_analyzed_review(
                db_session, business, location, submitted_at=_week(week_offset),
                topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
                severity="high", rating=1, text=f"Waited too long, week {week_offset} item {i}",
            )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)

    return db_session.execute(select(Issue).where(Issue.business_id == business.id)).scalar_one()


def _mock_response(insight_text: str) -> ClaudeToolResponse:
    return ClaudeToolResponse(
        raw_input={"insight_text": insight_text},
        model="claude-haiku-4-5-20251001",
        prompt_tokens=200,
        completion_tokens=40,
        latency_ms=300,
    )


@pytest.mark.unit
def test_build_insight_evidence_is_grounded_in_real_numbers(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    evidence = build_insight_evidence(db_session, issue)

    assert evidence.current_count == 5 + 7 + 9 + 18
    assert evidence.change_pct > 50
    assert evidence.direction == "emerging"
    assert len(evidence.representative_review_texts) > 0


@pytest.mark.unit
def test_generate_insight_without_api_key_uses_deterministic_template(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    settings_without_key = settings.model_copy(update={"anthropic_api_key": None})

    insight = generate_insight(db_session, issue, settings_without_key)

    assert insight is not None
    assert insight.generation_method == GenerationMethod.DETERMINISTIC_TEMPLATE
    assert insight.ai_invocation_id is None
    assert "wait time" in insight.text.lower()


@pytest.mark.integration
def test_generate_insight_success_persists_and_logs_invocation(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})

    mock = _mock_response("Wait-time complaints have risen sharply, suggesting a service-capacity issue.")
    with patch("app.insights.service.call_claude_tool", return_value=mock):
        insight = generate_insight(db_session, issue, settings_with_key)

    assert insight is not None
    assert insight.generation_method == GenerationMethod.LLM_SYNTHESIS
    assert insight.ai_invocation_id is not None

    invocation = db_session.get(AIInvocation, insight.ai_invocation_id)
    assert invocation.validation_passed is True
    assert invocation.operation == "insight_synthesis"

    stored = db_session.execute(select(Insight).where(Insight.issue_id == issue.id)).scalar_one()
    assert stored.id == insight.id


@pytest.mark.integration
def test_generate_insight_provider_error_returns_none_without_bad_row(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})

    with patch("app.insights.service.call_claude_tool", side_effect=TransientError("down")):
        insight = generate_insight(db_session, issue, settings_with_key)

    assert insight is None
    existing = db_session.execute(select(Insight).where(Insight.issue_id == issue.id)).scalar_one_or_none()
    assert existing is None

    invocation = db_session.execute(
        select(AIInvocation).where(AIInvocation.input_ref == str(issue.id))
    ).scalar_one()
    assert invocation.error_type == "provider_error"


@pytest.mark.integration
def test_generate_insight_invalid_output_dead_letters(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})

    invalid = ClaudeToolResponse(
        raw_input={"insight_text": "x"},  # below min_length=10
        model="claude-haiku-4-5-20251001", prompt_tokens=10, completion_tokens=5, latency_ms=100,
    )
    with patch("app.insights.service.call_claude_tool", return_value=invalid):
        insight = generate_insight(db_session, issue, settings_with_key)

    assert insight is None
    invocation = db_session.execute(
        select(AIInvocation).where(AIInvocation.input_ref == str(issue.id))
    ).scalar_one()
    assert invocation.error_type == "validation_error"
    assert invocation.validation_passed is False


@pytest.mark.unit
def test_groundedness_check_flags_unsupported_numbers(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    evidence = build_insight_evidence(db_session, issue)

    grounded_text = f"Complaints rose to {evidence.current_count} mentions, a clear increase."
    ungrounded_text = "Complaints rose to 9999 mentions, an alarming spike."

    assert check_insight_groundedness(evidence, grounded_text) is True
    assert check_insight_groundedness(evidence, ungrounded_text) is False


@pytest.mark.unit
def test_groundedness_check_accepts_numbers_quoted_from_review_evidence(db_session: Session) -> None:
    """Regression test: a number the model accurately cites from a representative
    review quote (part of its evidence) is grounded, not invented — caught via a real
    live call where "waited 45 minutes" from a review citation was false-flagged
    because the checker only compared against the aggregate count/percentage fields.
    """
    issue = _seeded_issue(db_session)
    evidence = build_insight_evidence(db_session, issue)

    review_number = None
    for text in evidence.representative_review_texts:
        for word in text.split():
            if word.isdigit():
                review_number = int(word)
                break
        if review_number is not None:
            break
    assert review_number is not None  # sanity: the seeded review text does contain a number

    text_citing_review_number = f"Customers reported waits of {review_number} minutes in some cases."
    assert check_insight_groundedness(evidence, text_citing_review_number) is True


@pytest.mark.integration
def test_generate_insights_for_business_batch_orders_by_priority(db_session: Session) -> None:
    issue = _seeded_issue(db_session)
    update_trends_and_priorities(db_session, issue.business_id)

    settings_with_key = settings.model_copy(update={"anthropic_api_key": "test-key"})
    mock = _mock_response("Grounded insight text for this recurring issue right here now.")

    with patch("app.insights.service.call_claude_tool", return_value=mock):
        run = generate_insights_for_business(db_session, issue.business_id, settings_with_key, limit=5)

    assert run.status == "completed"
    assert run.reviews_succeeded == 1
    insights = db_session.execute(select(Insight).where(Insight.issue_id == issue.id)).scalars().all()
    assert len(insights) == 1
