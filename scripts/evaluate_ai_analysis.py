"""CLI wrapper for evaluation.ai_quality.run_ai_quality_eval (Phase 3, consolidated
under evaluation/ in Phase 11). Spends one real Claude API call per hand-labeled
example in data/synthetic/eval_labels.json — see that module's docstring. Requires a
real ANTHROPIC_API_KEY.

Usage:
    python scripts/evaluate_ai_analysis.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from evaluation.ai_quality import REPORT_PATH, run_ai_quality_eval  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — cannot run the AI evaluation.")
        raise SystemExit(1)

    db = SessionLocal()
    try:
        report = run_ai_quality_eval(db, settings)
    finally:
        db.close()

    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))

    print(f"Overall sentiment accuracy: {report['overall_sentiment_accuracy']}")
    print(f"Aspect recall: {report['aspect_recall']}")
    print(f"Aspect sentiment accuracy: {report['aspect_sentiment_accuracy']}")
    print(f"Structured-output validity rate: {report['structured_output_validity_rate']}")
    print(f"Full report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
