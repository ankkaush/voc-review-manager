from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates, week_start
from app.issues.service import detect_recurring_issues, update_trends_and_priorities
from app.issues.trend import compute_trend
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.issue import Issue, IssueStatus, TrendDirection
from app.models.taxonomy import Aspect, Topic
from tests.factories import create_analyzed_review, create_business_and_location

_ANCHOR_MONDAY = week_start(datetime.now(UTC)) - timedelta(weeks=40)


def _week(offset: int) -> datetime:
    return datetime.combine(_ANCHOR_MONDAY + timedelta(weeks=offset, days=2), datetime.min.time(), tzinfo=UTC)


def _seed_reviews(db: Session, business, location, weekly_counts: list[int], **kwargs) -> None:
    for week_offset, count in enumerate(weekly_counts):
        for i in range(count):
            create_analyzed_review(
                db, business, location, submitted_at=_week(week_offset),
                aspect_sentiment="negative", rating=2,
                text=f"Complaint week {week_offset} item {i}", **kwargs,
            )


def _get_topic_aspect(db: Session, topic_key: str, aspect_key: str) -> tuple[Topic, Aspect]:
    topic = db.execute(select(Topic).where(Topic.key == topic_key)).scalar_one()
    aspect = db.execute(
        select(Aspect).where(Aspect.topic_id == topic.id, Aspect.key == aspect_key)
    ).scalar_one()
    return topic, aspect


@pytest.mark.unit
def test_emerging_pattern_is_classified_correctly(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    # 8 weeks: 4-week baseline flat at ~3, 4-week current rising sharply (mirrors §7's
    # seeded wait-time pattern: 5, 7, 9, 18).
    _seed_reviews(
        db_session, business, location, [3, 3, 3, 3, 5, 7, 9, 18],
        topic_key="service", aspect_key="wait_time",
    )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)
    update_trends_and_priorities(db_session, business.id)

    issue = db_session.execute(select(Issue).where(Issue.business_id == business.id)).scalar_one()

    assert issue.trend_direction == TrendDirection.EMERGING
    assert issue.trend_change_pct > 50
    assert issue.priority_score is not None
    assert issue.priority_score_breakdown["factors"]["trend"]["direction"] == TrendDirection.EMERGING


@pytest.mark.unit
def test_flat_pattern_is_classified_stable_not_emerging(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    _seed_reviews(
        db_session, business, location, [2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
        topic_key="price", aspect_key="price_value",
    )
    compute_weekly_aggregates(db_session, business.id)

    topic, aspect = _get_topic_aspect(db_session, "price", "price_value")

    # This flat series correctly never crosses the recurring-issue threshold (Phase 4),
    # so build a synthetic Issue directly purely to exercise the trend engine in
    # isolation against genuinely flat data.
    issue = Issue(
        business_id=business.id, location_id=location.id, topic_id=topic.id, aspect_id=aspect.id,
        title="test", description="test", status=IssueStatus.IDENTIFIED,
    )
    db_session.add(issue)
    db_session.commit()

    trend = compute_trend(db_session, issue)
    assert trend.direction == TrendDirection.STABLE
    assert abs(trend.change_pct) < 50

    metrics_exist = db_session.execute(
        select(AggregatePeriodMetric).where(AggregatePeriodMetric.business_id == business.id)
    ).scalars().all()
    assert len(metrics_exist) > 0  # sanity: aggregation actually produced data


@pytest.mark.unit
def test_declining_pattern_after_seeded_improvement(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)
    # Spike then improvement — mirrors §7's cleanliness-after-action pattern.
    _seed_reviews(
        db_session, business, location, [10, 12, 11, 9, 2, 1, 2, 1],
        topic_key="cleanliness", aspect_key="cleanliness_general",
    )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)
    update_trends_and_priorities(db_session, business.id)

    issue = db_session.execute(select(Issue).where(Issue.business_id == business.id)).scalar_one()

    assert issue.trend_direction == TrendDirection.DECLINING
    assert issue.trend_change_pct < -30


@pytest.mark.unit
def test_priority_ranks_severe_frequent_emerging_issue_above_mild_stable_one(db_session: Session) -> None:
    business, location = create_business_and_location(db_session)

    _seed_reviews(
        db_session, business, location, [3, 3, 3, 3, 8, 10, 14, 20],
        topic_key="service", aspect_key="wait_time", severity="high",
    )
    _seed_reviews(
        db_session, business, location, [2, 2, 2, 2, 2, 2, 2, 2],
        topic_key="price", aspect_key="price_value", severity="low",
    )
    compute_weekly_aggregates(db_session, business.id)
    detect_recurring_issues(db_session, business.id)
    update_trends_and_priorities(db_session, business.id)

    issues = {
        i.title: i
        for i in db_session.execute(select(Issue).where(Issue.business_id == business.id)).scalars().all()
    }

    wait_time_issue = next(i for t, i in issues.items() if "Wait Time" in t)
    # The flat/low-severity price pattern should not even be promoted to an Issue.
    assert not any("Price" in t for t in issues)
    assert wait_time_issue.priority_score > 0.5
