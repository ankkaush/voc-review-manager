"""AI quality evaluation (§6/§12 of ARCHITECTURE.md; consolidated in Phase 11).

Runs the real analysis pipeline against the ~40 hand-labeled examples in
data/synthetic/eval_labels.json and reports:
  - overall_sentiment exact-match accuracy
  - aspect recall (did the model find the aspects a human expected?)
  - aspect-sentiment accuracy (given a matched aspect, was its sentiment right?)
  - structured-output validity rate (fraction of Claude calls that validated
    without needing the one repair attempt)

This measures Claude's classification quality, not the deterministic control flow
around it — that's what tests/test_analysis.py (mocked) already covers. `run_ai_quality_eval`
requires a real ANTHROPIC_API_KEY and spends one real API call per example — it is
intentionally not wired into pytest or CI (§6: AI quality eval is non-blocking, and must
never run implicitly given this project's real API budget). `load_latest_report` only
reads the artifact already committed from the last time this was run — use that for the
consolidated Phase 11 report instead of re-running the eval.
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.service import TaxonomyLookup, analyze_review
from app.config import Settings
from app.models.ai_invocation import AIInvocation
from app.models.review import AnalysisStatus, Review
from app.models.review_analysis import ReviewAnalysis, ReviewAspect
from app.models.taxonomy import Aspect, Topic

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
REPORT_PATH = DATA_DIR / "eval_report.json"


def load_eval_labels() -> list[dict]:
    return json.loads((DATA_DIR / "eval_labels.json").read_text())


def load_latest_report() -> dict | None:
    """Reads the eval report artifact from the last real run of `run_ai_quality_eval`,
    without spending any API budget. Returns None if it has never been generated.
    """
    if not REPORT_PATH.exists():
        return None
    report = json.loads(REPORT_PATH.read_text())
    report.pop("per_example", None)
    return report


def run_ai_quality_eval(db: Session, settings: Settings) -> dict:
    """Spends one real Claude API call per hand-labeled example. Never call this from
    a test or from CI — it is a deliberately manual, opt-in script (see
    scripts/evaluate_ai_analysis.py) given the project's real API budget constraint.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot run the AI evaluation.")

    labels = load_eval_labels()
    taxonomy = TaxonomyLookup(db)
    topic_keys = {t.id: t.key for t in db.execute(select(Topic)).scalars().all()}
    aspect_keys = {a.id: a.key for a in db.execute(select(Aspect)).scalars().all()}

    results = []

    for label in labels:
        review = db.execute(
            select(Review).where(Review.source_review_id == label["source_review_id"])
        ).scalar_one_or_none()
        if review is None:
            results.append({"source_review_id": label["source_review_id"], "skipped": "review not found"})
            continue

        # Force a fresh analysis for this evaluation run — delete any prior
        # ReviewAnalysis/ReviewAspect rows so re-running this script is idempotent
        # (ReviewAnalysis has a unique constraint on review_id).
        existing = db.execute(
            select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
        ).scalar_one_or_none()
        if existing is not None:
            db.execute(ReviewAspect.__table__.delete().where(ReviewAspect.review_analysis_id == existing.id))
            db.delete(existing)
        review.analysis_status = AnalysisStatus.PENDING
        db.commit()

        analyze_review(db, review, settings, taxonomy)

        analysis = db.execute(
            select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
        ).scalar_one_or_none()

        if analysis is None:
            results.append(
                {
                    "source_review_id": label["source_review_id"],
                    "outcome": "dead_lettered",
                    "correct_sentiment": False,
                }
            )
            continue

        actual_aspects = db.execute(
            select(ReviewAspect).where(ReviewAspect.review_analysis_id == analysis.id)
        ).scalars().all()
        actual_pairs = {
            (topic_keys[a.topic_id], aspect_keys[a.aspect_id]): a.aspect_sentiment for a in actual_aspects
        }

        expected_aspects = {(a["aspect"], a["sentiment"]) for a in label["expected_aspects"]}
        expected_aspect_keys = {aspect_key for aspect_key, _ in expected_aspects}
        actual_aspect_keys = {aspect_key for _, aspect_key in actual_pairs}
        matched_aspect_keys = expected_aspect_keys & actual_aspect_keys

        aspect_sentiment_hits = 0
        for aspect_key, expected_sentiment in expected_aspects:
            actual_sentiment = next(
                (sent for (_, ak), sent in actual_pairs.items() if ak == aspect_key), None
            )
            if actual_sentiment == expected_sentiment:
                aspect_sentiment_hits += 1

        results.append(
            {
                "source_review_id": label["source_review_id"],
                "category": label["category"],
                "expected_sentiment": label["expected_overall_sentiment"],
                "actual_sentiment": analysis.overall_sentiment,
                "correct_sentiment": analysis.overall_sentiment == label["expected_overall_sentiment"],
                "expected_aspect_count": len(expected_aspects),
                "matched_aspect_count": len(matched_aspect_keys),
                "aspect_sentiment_hits": aspect_sentiment_hits,
            }
        )

    review_ids = [
        r.id
        for r in db.execute(
            select(Review).where(
                Review.source_review_id.in_([label_row["source_review_id"] for label_row in labels])
            )
        ).scalars().all()
    ]
    all_calls = db.execute(
        select(AIInvocation).where(AIInvocation.input_ref.in_([str(rid) for rid in review_ids]))
    ).scalars().all()
    validity_hits = sum(1 for inv in all_calls if inv.validation_passed)
    validity_rate = validity_hits / len(all_calls) if all_calls else None

    scored = [r for r in results if "correct_sentiment" in r]
    sentiment_accuracy = sum(1 for r in scored if r["correct_sentiment"]) / len(scored) if scored else None

    aspect_scored = [r for r in scored if r.get("expected_aspect_count", 0) > 0]
    matched_total = sum(r["matched_aspect_count"] for r in aspect_scored)
    expected_total = sum(r["expected_aspect_count"] for r in aspect_scored)
    aspect_recall = matched_total / expected_total if aspect_scored else None
    aspect_sentiment_accuracy = (
        sum(r["aspect_sentiment_hits"] for r in aspect_scored)
        / sum(r["expected_aspect_count"] for r in aspect_scored)
        if aspect_scored
        else None
    )

    return {
        "total_examples": len(labels),
        "scored_examples": len(scored),
        "overall_sentiment_accuracy": sentiment_accuracy,
        "aspect_recall": aspect_recall,
        "aspect_sentiment_accuracy": aspect_sentiment_accuracy,
        "structured_output_validity_rate": validity_rate,
        "total_ai_calls_made": len(all_calls),
        "per_example": results,
    }
