"""CLI entrypoint chaining aggregation + recurring-issue detection — a stand-in for
Phase 10's scheduled jobs. Requires reviews to have already been analyzed (Phase 3);
run scripts/run_analysis.py first if `analysis_status` is still mostly `pending`.

Usage:
    python scripts/run_aggregation.py --business-name "The Local Table"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.aggregation.service import compute_weekly_aggregates  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.issues.service import detect_recurring_issues  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.processing_run import ProcessingRunTrigger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-name", default="The Local Table")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        business = db.execute(
            select(Business).where(Business.name == args.business_name)
        ).scalar_one_or_none()
        if business is None:
            print(f"No business named {args.business_name!r} found.")
            raise SystemExit(1)

        agg_run = compute_weekly_aggregates(db, business.id, trigger=ProcessingRunTrigger.MANUAL)
        print(
            f"aggregation: processing_run_id={agg_run.id} status={agg_run.status.value} "
            f"analyzed_reviews={agg_run.reviews_in_scope}"
        )

        issue_run = detect_recurring_issues(db, business.id, trigger=ProcessingRunTrigger.MANUAL)
        print(
            f"issue_detection: processing_run_id={issue_run.id} status={issue_run.status.value} "
            f"combinations_checked={issue_run.reviews_in_scope} issues_touched={issue_run.reviews_succeeded}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
