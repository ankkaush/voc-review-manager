from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates, week_start
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.location import Location
from tests.factories import create_analyzed_review, create_business_and_location, resolve_topic_aspect

# A fixed Monday anchor so every test controls exactly which calendar week a review
# lands in, independent of whatever day the test happens to run on.
_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=10)


def _week(offset: int) -> datetime:
    """Wednesday of the anchor week + offset weeks — always buckets to that week."""
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


@pytest.mark.unit
def test_compute_weekly_aggregates_counts_are_exact(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    # Week 0: 2 negative + 1 positive wait_time mentions, ratings 1,2,5.
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="service", aspect_key="wait_time", aspect_sentiment="negative", rating=1,
    )
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="service", aspect_key="wait_time", aspect_sentiment="negative", rating=2,
    )
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="service", aspect_key="wait_time", aspect_sentiment="positive", rating=5,
    )

    run = compute_weekly_aggregates(db_session, business.id)
    assert run.status == "completed"

    topic_id, aspect_id = resolve_topic_aspect(db_session, "service", "wait_time")
    metric = db_session.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business.id,
            AggregatePeriodMetric.location_id == location.id,
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
            AggregatePeriodMetric.period_start == _ANCHOR_MONDAY,
        )
    ).scalar_one()

    assert metric.mention_count == 3
    assert metric.negative_count == 2
    assert metric.positive_count == 1
    assert metric.neutral_count == 0
    assert metric.avg_rating == pytest.approx((1 + 2 + 5) / 3)
    assert metric.period_end == _ANCHOR_MONDAY + timedelta(days=6)


@pytest.mark.unit
def test_compute_weekly_aggregates_separates_different_weeks(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="food", aspect_key="food_quality", aspect_sentiment="positive", rating=5,
    )
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(1),
        topic_key="food", aspect_key="food_quality", aspect_sentiment="positive", rating=4,
    )

    compute_weekly_aggregates(db_session, business.id)

    topic_id, aspect_id = resolve_topic_aspect(db_session, "food", "food_quality")
    metrics = db_session.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business.id,
            AggregatePeriodMetric.location_id == location.id,
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
        )
    ).scalars().all()

    assert len(metrics) == 2
    assert {m.period_start for m in metrics} == {_ANCHOR_MONDAY, _ANCHOR_MONDAY + timedelta(weeks=1)}
    assert all(m.mention_count == 1 for m in metrics)


@pytest.mark.unit
def test_compute_weekly_aggregates_creates_business_wide_rollup(db_session: Session) -> None:
    business, location_a = create_business_and_location(db_session, "A")
    location_b = Location(business_id=business.id, name="Second Location", city="Springfield")
    db_session.add(location_b)
    db_session.commit()

    create_analyzed_review(
        db_session, business, location_a, submitted_at=_week(0),
        topic_key="cleanliness", aspect_key="cleanliness_general", aspect_sentiment="negative", rating=2,
    )
    create_analyzed_review(
        db_session, business, location_b, submitted_at=_week(0),
        topic_key="cleanliness", aspect_key="cleanliness_general", aspect_sentiment="negative", rating=1,
    )

    compute_weekly_aggregates(db_session, business.id)

    topic_id, aspect_id = resolve_topic_aspect(db_session, "cleanliness", "cleanliness_general")
    business_wide = db_session.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business.id,
            AggregatePeriodMetric.location_id.is_(None),
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
            AggregatePeriodMetric.period_start == _ANCHOR_MONDAY,
        )
    ).scalar_one()

    assert business_wide.mention_count == 2
    assert business_wide.negative_count == 2


@pytest.mark.integration
def test_compute_weekly_aggregates_upserts_in_place_on_rerun(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="price", aspect_key="price_value", aspect_sentiment="negative", rating=2,
    )

    compute_weekly_aggregates(db_session, business.id)
    topic_id, aspect_id = resolve_topic_aspect(db_session, "price", "price_value")
    first = db_session.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business.id,
            AggregatePeriodMetric.location_id == location.id,
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
        )
    ).scalar_one()
    first_id = first.id

    # A second review lands in the same week before the aggregation job re-runs.
    create_analyzed_review(
        db_session, business, location, submitted_at=_week(0),
        topic_key="price", aspect_key="price_value", aspect_sentiment="negative", rating=3,
    )
    compute_weekly_aggregates(db_session, business.id)

    all_rows = db_session.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == business.id,
            AggregatePeriodMetric.location_id == location.id,
            AggregatePeriodMetric.topic_id == topic_id,
            AggregatePeriodMetric.aspect_id == aspect_id,
        )
    ).scalars().all()

    assert len(all_rows) == 1  # updated in place, not duplicated
    assert all_rows[0].id == first_id  # same row identity — FK-stable for IssueEvidence
    assert all_rows[0].mention_count == 2
