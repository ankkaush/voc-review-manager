"""Explainable priority scoring (§D, §Open-Question-3-resolved).

Weights are configuration values, not fixed in Phase 0 — finalized here, in Phase 5, and
tested against the seeded dataset's expected issue ordering (tests/test_priority.py). No
ML model: every factor and its contribution is stored in `priority_score_breakdown` so a
manager (or an interviewer) can see exactly why one issue outranks another.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.issues.trend import TrendResult
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.issue import Issue, IssueStatus, TrendDirection
from app.models.location import Location

# Configurable, documented, deterministic (§Open-Question-3): frequency and severity
# carry the most weight (a loud, serious problem matters most), trend and rating impact
# next (is it getting worse, is it hurting satisfaction), persistence and location
# spread carry the least (secondary signals of how entrenched/widespread it is).
PRIORITY_WEIGHTS: dict[str, float] = {
    "frequency": 0.25,
    "severity": 0.20,
    "trend": 0.20,
    "rating_impact": 0.15,
    "persistence": 0.10,
    "location_spread": 0.10,
}

FREQUENCY_SCALE = 20  # 20+ negative mentions in the current period = max frequency score
PERSISTENCE_SCALE = 8  # 8+ weeks of any negative activity = fully persistent
SEVERITY_SCORES = {"high": 1.0, "medium": 0.6, "low": 0.3, None: 0.0}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _frequency_score(current_negative_count: int) -> float:
    return _clamp(current_negative_count / FREQUENCY_SCALE, 0.0, 1.0)


def _severity_score(severity: str | None) -> float:
    return SEVERITY_SCORES.get(severity, 0.0)


def _trend_score(trend: TrendResult) -> float:
    if trend.change_pct is not None:
        return _clamp(trend.change_pct / 200.0, -1.0, 1.0)
    return {
        TrendDirection.EMERGING: 1.0,
        TrendDirection.NEW: 0.5,
        TrendDirection.STABLE: 0.0,
        TrendDirection.DECLINING: -1.0,
        TrendDirection.INSUFFICIENT_DATA: 0.0,
    }[trend.direction]


def _rating_impact_score(db: Session, issue: Issue, trend: TrendResult) -> tuple[float, float | None]:
    if trend.current_period_start is None:
        return 0.0, None

    metrics = db.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == issue.business_id,
            AggregatePeriodMetric.location_id == issue.location_id,
            AggregatePeriodMetric.topic_id == issue.topic_id,
            AggregatePeriodMetric.aspect_id == issue.aspect_id,
            AggregatePeriodMetric.period_start >= trend.current_period_start,
            AggregatePeriodMetric.period_start <= trend.current_period_end,
        )
    ).scalars().all()

    weighted_sum, weight_total = 0.0, 0
    for m in metrics:
        if m.avg_rating is not None:
            weighted_sum += m.avg_rating * m.mention_count
            weight_total += m.mention_count

    if weight_total == 0:
        return 0.0, None

    avg_rating = weighted_sum / weight_total
    return _clamp((3.0 - avg_rating) / 2.0, 0.0, 1.0), avg_rating


def _persistence_score(db: Session, issue: Issue) -> tuple[float, int]:
    weeks_with_activity = db.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == issue.business_id,
            AggregatePeriodMetric.location_id == issue.location_id,
            AggregatePeriodMetric.topic_id == issue.topic_id,
            AggregatePeriodMetric.aspect_id == issue.aspect_id,
            AggregatePeriodMetric.negative_count > 0,
        )
    ).scalars().all()
    count = len(weeks_with_activity)
    return _clamp(count / PERSISTENCE_SCALE, 0.0, 1.0), count


def _location_spread_score(db: Session, issue: Issue) -> tuple[float, int, int]:
    sibling_locations = db.execute(
        select(Issue.location_id).where(
            Issue.business_id == issue.business_id,
            Issue.topic_id == issue.topic_id,
            Issue.aspect_id == issue.aspect_id,
            Issue.status.not_in([IssueStatus.RESOLVED, IssueStatus.CLOSED, IssueStatus.REJECTED]),
        )
    ).scalars().all()
    spread_count = len(set(sibling_locations))

    total_locations = db.execute(
        select(Location).where(Location.business_id == issue.business_id)
    ).scalars().all()
    total = len(total_locations) or 1

    return _clamp(spread_count / total, 0.0, 1.0), spread_count, total


@dataclass
class PriorityResult:
    score: float
    breakdown: dict


def compute_priority(db: Session, issue: Issue, trend: TrendResult) -> PriorityResult:
    frequency = _frequency_score(trend.current_negative_count)
    severity = _severity_score(issue.severity)
    trend_score = _trend_score(trend)
    rating_impact, avg_rating = _rating_impact_score(db, issue, trend)
    persistence, weeks_with_activity = _persistence_score(db, issue)
    location_spread, spread_count, total_locations = _location_spread_score(db, issue)

    factors = {
        "frequency": {"raw": trend.current_negative_count, "score": frequency},
        "severity": {"raw": issue.severity, "score": severity},
        "trend": {"raw": trend.change_pct, "direction": trend.direction, "score": trend_score},
        "rating_impact": {"raw": avg_rating, "score": rating_impact},
        "persistence": {"raw": weeks_with_activity, "score": persistence},
        "location_spread": {
            "raw": f"{spread_count}/{total_locations} locations",
            "score": location_spread,
        },
    }

    score = 0.0
    for name, factor in factors.items():
        weight = PRIORITY_WEIGHTS[name]
        contribution = weight * factor["score"]
        factor["weight"] = weight
        factor["contribution"] = contribution
        score += contribution

    breakdown = {"priority_score": score, "weights": PRIORITY_WEIGHTS, "factors": factors}
    return PriorityResult(score=score, breakdown=breakdown)
