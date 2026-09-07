"""Scheduled pipeline entrypoint (Phase 10): what a Render Cron Job runs periodically.

Chains aggregation -> issue detection -> trend/priority recompute, all deterministic
and free. Analysis (Phase 3) and insight generation (Phase 5) are AI-touching and cost
real money per item, so they're OFF by default here — a periodic cron job must never
silently burn API budget. Pass --analyze-limit / --generate-insights explicitly to
include them, with small limits.

Every run uses ProcessingRunTrigger.CRON (vs. MANUAL for the same call made through the
API) — the exact same underlying service functions either way, which is what
tests/test_pipeline.py verifies: a cron-triggered run produces identical results to an
equivalent manually-triggered one (§10 DoD).

Usage:
    python scripts/run_pipeline.py --business-name "The Local Table"
    python scripts/run_pipeline.py --analyze-limit 20 --generate-insights --insights-limit 3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.actions.outcome_service import evaluate_outcomes_for_business  # noqa: E402
from app.aggregation.service import compute_weekly_aggregates  # noqa: E402
from app.analysis.service import analyze_pending_reviews  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.insights.service import generate_insights_for_business  # noqa: E402
from app.issues.service import detect_recurring_issues, update_trends_and_priorities  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.processing_run import ProcessingRunTrigger  # noqa: E402


def run_pipeline(
    business_name: str,
    analyze_limit: int = 0,
    generate_insights: bool = False,
    insights_limit: int = 3,
) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        business = db.execute(
            select(Business).where(Business.name == business_name)
        ).scalar_one_or_none()
        if business is None:
            print(f"No business named {business_name!r} found.")
            raise SystemExit(1)

        if analyze_limit > 0:
            run = analyze_pending_reviews(
                db, settings, limit=analyze_limit, trigger=ProcessingRunTrigger.CRON
            )
            print(
                f"analyze: status={run.status.value} "
                f"succeeded={run.reviews_succeeded} failed={run.reviews_failed}"
            )
        else:
            print("analyze: skipped (--analyze-limit not set — AI calls are opt-in for scheduled runs)")

        agg_run = compute_weekly_aggregates(db, business.id, trigger=ProcessingRunTrigger.CRON)
        print(f"aggregate: status={agg_run.status.value} analyzed_reviews={agg_run.reviews_in_scope}")

        issue_run = detect_recurring_issues(db, business.id, trigger=ProcessingRunTrigger.CRON)
        print(
            f"issue_detection: status={issue_run.status.value} "
            f"combinations_checked={issue_run.reviews_in_scope}"
        )

        trend_run = update_trends_and_priorities(db, business.id, trigger=ProcessingRunTrigger.CRON)
        print(f"trend: status={trend_run.status.value} issues_updated={trend_run.reviews_succeeded}")

        outcome_run = evaluate_outcomes_for_business(db, business.id, trigger=ProcessingRunTrigger.CRON)
        print(f"outcome: status={outcome_run.status.value} actions_evaluated={outcome_run.reviews_succeeded}")

        if generate_insights:
            insight_run = generate_insights_for_business(
                db, business.id, settings, limit=insights_limit, trigger=ProcessingRunTrigger.CRON
            )
            print(f"insight: status={insight_run.status.value} generated={insight_run.reviews_succeeded}")
        else:
            print("insight: skipped (--generate-insights not set — AI calls are opt-in for scheduled runs)")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-name", default="The Local Table")
    parser.add_argument(
        "--analyze-limit", type=int, default=0,
        help="Analyze up to N pending reviews (costs one API call each). Default 0 = skip.",
    )
    parser.add_argument(
        "--generate-insights", action="store_true",
        help="Generate insights for the highest-priority open issues (costs one API call each).",
    )
    parser.add_argument("--insights-limit", type=int, default=3)
    args = parser.parse_args()

    run_pipeline(
        business_name=args.business_name,
        analyze_limit=args.analyze_limit,
        generate_insights=args.generate_insights,
        insights_limit=args.insights_limit,
    )


if __name__ == "__main__":
    main()
