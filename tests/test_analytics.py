"""End-to-end analytics tests (Phase 9 DoD): every dashboard panel's numbers are
asserted against source-of-truth queries computed independently in the test itself.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.analytics.service import get_overview, get_top_aspects
from tests.factories import create_analyzed_review, create_business_and_location

_NOW = datetime.now(UTC)


@pytest.mark.integration
def test_overview_matches_hand_computed_source_of_truth(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    reviews = [
        create_analyzed_review(
            db_session, business, location, submitted_at=_NOW - timedelta(days=i),
            topic_key="food", aspect_key="food_quality", aspect_sentiment="positive",
            overall_sentiment="positive", rating=5, text=f"Great food {i}",
        )
        for i in range(3)
    ] + [
        create_analyzed_review(
            db_session, business, location, submitted_at=_NOW - timedelta(days=i),
            topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
            overall_sentiment="negative", rating=1, text=f"Slow service {i}",
        )
        for i in range(2)
    ]

    overview = get_overview(db_session, business.id)

    # Independently computed expectations, not just re-running the same code.
    expected_ratings = Counter(str(r.rating) for r in reviews)
    expected_sentiments = Counter(["positive"] * 3 + ["negative"] * 2)

    assert overview.review_count == len(reviews)
    assert overview.rating_distribution == dict(expected_ratings)
    assert overview.sentiment_distribution == dict(expected_sentiments)
    assert overview.ingestion_status_counts == {"accepted": 5}
    assert overview.analysis_status_counts == {"analyzed": 5}
    assert overview.language_distribution == {}  # factory doesn't set detected_language


@pytest.mark.integration
def test_overview_with_zero_reviews_is_all_zero(db_session: Session) -> None:
    business, _location = create_business_and_location(db_session)
    overview = get_overview(db_session, business.id)

    assert overview.review_count == 0
    assert overview.rating_distribution == {}
    assert overview.sentiment_distribution == {}


@pytest.mark.integration
def test_top_aspects_matches_hand_computed_counts(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    for i in range(5):
        create_analyzed_review(
            db_session, business, location, submitted_at=_NOW - timedelta(days=i),
            topic_key="service", aspect_key="wait_time", aspect_sentiment="negative",
            rating=1, text=f"Slow {i}",
        )
    for i in range(3):
        create_analyzed_review(
            db_session, business, location, submitted_at=_NOW - timedelta(days=i),
            topic_key="food", aspect_key="food_quality", aspect_sentiment="positive",
            rating=5, text=f"Great {i}",
        )
    for i in range(1):
        create_analyzed_review(
            db_session, business, location, submitted_at=_NOW - timedelta(days=i),
            topic_key="price", aspect_key="price_value", aspect_sentiment="negative",
            rating=2, text=f"Pricey {i}",
        )

    result = get_top_aspects(db_session, business.id, limit=10)

    negative_by_aspect = {s.aspect_key: s.negative_count for s in result.top_negative}
    positive_by_aspect = {s.aspect_key: s.positive_count for s in result.top_positive}

    assert negative_by_aspect == {"wait_time": 5, "price_value": 1}
    assert positive_by_aspect == {"food_quality": 3}
    # Ranked correctly, most-mentioned negative aspect first.
    assert result.top_negative[0].aspect_key == "wait_time"


@pytest.mark.integration
def test_top_aspects_respects_limit_and_excludes_zero_counts(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    create_analyzed_review(
        db_session, business, location, submitted_at=_NOW,
        topic_key="food", aspect_key="food_quality", aspect_sentiment="positive", rating=5,
    )
    # Only a positive mention exists — must not appear in top_negative at all.
    result = get_top_aspects(db_session, business.id, limit=10)
    assert result.top_negative == []
    assert len(result.top_positive) == 1


@pytest.mark.integration
def test_analytics_endpoints_require_auth(client) -> None:
    import uuid

    response = client.get(f"/analytics/overview?business_id={uuid.uuid4()}")
    assert response.status_code == 401
