"""Deterministic trend detection (§8 kickoff spec, §D: explainable statistics, not ML).

Compares the most recent 4 weeks of negative mentions against the preceding 4-week
baseline for an issue's (topic, aspect, location) scope — the same "previous four-week
baseline" framing as the original business example ("waiting-time complaints increased
142% compared with the previous four-week baseline"). No anomaly-detection black box:
every number here is a plain sum/percentage computed from AggregatePeriodMetric.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.issue import Issue, TrendDirection

CURRENT_WINDOW_WEEKS = 4
BASELINE_WINDOW_WEEKS = 4
EMERGING_THRESHOLD_PCT = 50.0
DECLINING_THRESHOLD_PCT = -30.0


@dataclass
class TrendResult:
    current_period_start: date | None
    current_period_end: date | None
    current_negative_count: int
    baseline_period_start: date | None
    baseline_period_end: date | None
    baseline_negative_count: int
    change_pct: float | None
    direction: TrendDirection


def compute_trend(db: Session, issue: Issue) -> TrendResult:
    metrics = db.execute(
        select(AggregatePeriodMetric)
        .where(
            AggregatePeriodMetric.business_id == issue.business_id,
            AggregatePeriodMetric.location_id == issue.location_id,
            AggregatePeriodMetric.topic_id == issue.topic_id,
            AggregatePeriodMetric.aspect_id == issue.aspect_id,
        )
        .order_by(AggregatePeriodMetric.period_start)
    ).scalars().all()

    if not metrics:
        return TrendResult(None, None, 0, None, None, 0, None, TrendDirection.INSUFFICIENT_DATA)

    by_week = {m.period_start: m for m in metrics}
    latest_week = metrics[-1].period_start

    current_weeks = [latest_week - timedelta(weeks=i) for i in range(CURRENT_WINDOW_WEEKS)]
    baseline_weeks = [
        latest_week - timedelta(weeks=i)
        for i in range(CURRENT_WINDOW_WEEKS, CURRENT_WINDOW_WEEKS + BASELINE_WINDOW_WEEKS)
    ]

    current_count = sum(by_week[w].negative_count for w in current_weeks if w in by_week)
    current_start, current_end = min(current_weeks), max(current_weeks) + timedelta(days=6)

    baseline_weeks_present = [w for w in baseline_weeks if w in by_week]
    if not baseline_weeks_present:
        return TrendResult(
            current_start, current_end, current_count, None, None, 0, None, TrendDirection.NEW
        )

    baseline_count = sum(by_week[w].negative_count for w in baseline_weeks_present)
    baseline_start, baseline_end = min(baseline_weeks), max(baseline_weeks) + timedelta(days=6)

    if baseline_count == 0:
        direction = TrendDirection.EMERGING if current_count > 0 else TrendDirection.STABLE
        return TrendResult(
            current_start, current_end, current_count,
            baseline_start, baseline_end, baseline_count, None, direction,
        )

    change_pct = (current_count - baseline_count) / baseline_count * 100.0
    if change_pct >= EMERGING_THRESHOLD_PCT:
        direction = TrendDirection.EMERGING
    elif change_pct <= DECLINING_THRESHOLD_PCT:
        direction = TrendDirection.DECLINING
    else:
        direction = TrendDirection.STABLE

    return TrendResult(
        current_start, current_end, current_count,
        baseline_start, baseline_end, baseline_count, change_pct, direction,
    )
