"""Deterministic outcome tracking (§3, §7 kickoff spec: "did the situation improve").

Compares negative-mention volume in the weeks immediately before an action's
resolution against the weeks immediately after — same explainable-statistics approach
as Phase 5's trend engine, deliberately not a new technique. The one subtlety this
module exists to get right: "no negative mentions after" (genuine improvement) is not
the same as "no reviews at all after" (not enough time has passed yet to know) — the
two look identical if you only look at `negative_count`, so this checks total
`mention_count` for the after-period first to tell them apart.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aggregation.service import week_start
from app.models.action import Action
from app.models.aggregate_period_metric import AggregatePeriodMetric
from app.models.issue import Issue
from app.models.outcome import OutcomeInterpretation

WINDOW_WEEKS = 4
IMPROVEMENT_THRESHOLD_PCT = -30.0
WORSENING_THRESHOLD_PCT = 30.0


@dataclass
class OutcomeResult:
    before_period_start: date
    before_period_end: date
    before_negative_count: int
    after_period_start: date | None
    after_period_end: date | None
    after_negative_count: int | None
    delta_pct: float | None
    interpretation: OutcomeInterpretation


def compute_outcome(db: Session, action: Action) -> OutcomeResult:
    issue = db.get(Issue, action.issue_id)

    resolved_week = week_start(action.resolved_at)
    before_weeks = [resolved_week - timedelta(weeks=i) for i in range(1, WINDOW_WEEKS + 1)]
    after_weeks = [resolved_week + timedelta(weeks=i) for i in range(1, WINDOW_WEEKS + 1)]

    metrics = db.execute(
        select(AggregatePeriodMetric).where(
            AggregatePeriodMetric.business_id == issue.business_id,
            AggregatePeriodMetric.location_id == issue.location_id,
            AggregatePeriodMetric.topic_id == issue.topic_id,
            AggregatePeriodMetric.aspect_id == issue.aspect_id,
        )
    ).scalars().all()
    by_week = {m.period_start: m for m in metrics}

    before_start, before_end = min(before_weeks), max(before_weeks) + timedelta(days=6)
    before_negative_count = sum(by_week[w].negative_count for w in before_weeks if w in by_week)

    after_start, after_end = min(after_weeks), max(after_weeks) + timedelta(days=6)
    after_present = [by_week[w] for w in after_weeks if w in by_week]
    after_total_mentions = sum(m.mention_count for m in after_present)

    if after_total_mentions == 0:
        # Either not enough time has passed since resolution, or genuinely zero
        # reviews of any kind — either way, there's no basis to claim an outcome yet.
        return OutcomeResult(
            before_period_start=before_start, before_period_end=before_end,
            before_negative_count=before_negative_count,
            after_period_start=after_start, after_period_end=after_end,
            after_negative_count=None, delta_pct=None,
            interpretation=OutcomeInterpretation.INSUFFICIENT_DATA,
        )

    after_negative_count = sum(m.negative_count for m in after_present)

    if before_negative_count == 0:
        interpretation = (
            OutcomeInterpretation.NO_SIGNIFICANT_CHANGE
            if after_negative_count == 0
            else OutcomeInterpretation.WORSENED
        )
        delta_pct = None
    else:
        delta_pct = (after_negative_count - before_negative_count) / before_negative_count * 100.0
        if delta_pct <= IMPROVEMENT_THRESHOLD_PCT:
            interpretation = OutcomeInterpretation.IMPROVED
        elif delta_pct >= WORSENING_THRESHOLD_PCT:
            interpretation = OutcomeInterpretation.WORSENED
        else:
            interpretation = OutcomeInterpretation.NO_SIGNIFICANT_CHANGE

    return OutcomeResult(
        before_period_start=before_start, before_period_end=before_end,
        before_negative_count=before_negative_count,
        after_period_start=after_start, after_period_end=after_end,
        after_negative_count=after_negative_count, delta_pct=delta_pct,
        interpretation=interpretation,
    )
