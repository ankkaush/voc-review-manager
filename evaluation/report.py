"""Builds the consolidated Phase 11 evaluation report — a single markdown artifact
combining the deterministic test suite's results with the AI-quality eval's last-run
numbers, so there is one documented, defensible answer to "how do you know this
works," instead of scattered per-phase notes.

`build_report` is pure and deterministic (no subprocess, no API, no DB) so it can be
unit-tested directly. `evaluation/generate_report.py` is the script that actually
gathers `test_summary` (by shelling out to pytest) and `ai_quality` (by reading the
committed eval_report.json artifact — never by re-running the real-API eval) and
writes the result to evaluation/EVAL_REPORT.md.
"""

from datetime import datetime


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def build_report(test_summary: dict, ai_quality: dict | None, generated_at: datetime) -> str:
    lines = [
        "# Evaluation Report",
        "",
        f"Generated: {generated_at.isoformat()}",
        "",
        "## Deterministic test suite",
        "",
        "Every non-AI code path (ingestion, aggregation, issue detection, trend/priority, "
        "workflow, outcomes, notifications, pipeline orchestration, API routes) is covered "
        "by pytest and is fully reproducible — no API cost, safe to run in CI on every commit.",
        "",
        "| Marker | Passed | Failed | Total |",
        "|---|---|---|---|",
    ]
    total_passed = total_failed = 0
    for marker in ("unit", "integration", "e2e"):
        summary = test_summary.get(marker, {"passed": 0, "failed": 0})
        passed, failed = summary["passed"], summary["failed"]
        total_passed += passed
        total_failed += failed
        lines.append(f"| {marker} | {passed} | {failed} | {passed + failed} |")
    total_all = total_passed + total_failed
    lines.append(f"| **total** | **{total_passed}** | **{total_failed}** | **{total_all}** |")
    lines.append("")
    if total_failed == 0:
        lines.append("**Result: PASSING**")
    else:
        lines.append(f"**Result: {total_failed} FAILING — see details above**")
    lines.append("")

    lines.append("## AI quality evaluation")
    lines.append("")
    if ai_quality is None:
        lines.append(
            "No AI-quality eval report found. Run `python scripts/evaluate_ai_analysis.py` "
            "to generate one — note this spends one real Claude API call per hand-labeled "
            "example (data/synthetic/eval_labels.json), so it is a deliberate, manual, "
            "non-CI step (§6: AI quality eval is non-blocking)."
        )
    else:
        lines.extend(
            [
                "Measures Claude's classification quality against "
                f"{ai_quality.get('total_examples', 'N')} hand-labeled examples "
                "(data/synthetic/eval_labels.json) — a one-time real-API run, not "
                "re-executed on every commit, per the project's API budget constraint "
                "(ADR-9: evaluation built incrementally per phase).",
                "",
                "| Metric | Value |",
                "|---|---|",
                f"| Examples scored | {ai_quality.get('scored_examples', 'n/a')} / "
                f"{ai_quality.get('total_examples', 'n/a')} |",
                f"| Overall sentiment accuracy | {_pct(ai_quality.get('overall_sentiment_accuracy'))} |",
                f"| Aspect recall | {_pct(ai_quality.get('aspect_recall'))} |",
                f"| Aspect-sentiment accuracy | {_pct(ai_quality.get('aspect_sentiment_accuracy'))} |",
                "| Structured-output validity rate | "
                f"{_pct(ai_quality.get('structured_output_validity_rate'))} |",
                f"| Total AI calls made in that run | {ai_quality.get('total_ai_calls_made', 'n/a')} |",
            ]
        )
    lines.append("")

    return "\n".join(lines)
