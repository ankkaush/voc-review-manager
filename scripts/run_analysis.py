"""CLI entrypoint for running AI analysis over pending reviews — a stand-in for
Phase 10's scheduled cron job (the underlying call is identical either way).

Usage:
    python scripts/run_analysis.py --limit 200
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analysis.service import analyze_pending_reviews  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.processing_run import ProcessingRunTrigger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — cannot run live analysis. Set it in .env first.")
        raise SystemExit(1)

    db = SessionLocal()
    try:
        run = analyze_pending_reviews(db, settings, limit=args.limit, trigger=ProcessingRunTrigger.MANUAL)
        print(
            f"processing_run_id={run.id} status={run.status} "
            f"in_scope={run.reviews_in_scope} succeeded={run.reviews_succeeded} failed={run.reviews_failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
