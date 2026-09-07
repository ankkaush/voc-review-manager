"""Phase 11: evaluation.report.build_report is pure and deterministic — no subprocess,
no API, no DB — so it's tested directly with synthetic inputs.
"""

from datetime import UTC, datetime

import pytest

from evaluation.report import build_report

_NOW = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.mark.unit
def test_report_shows_passing_when_no_failures() -> None:
    summary = {
        "unit": {"passed": 29, "failed": 0},
        "integration": {"passed": 43, "failed": 0},
        "e2e": {"passed": 0, "failed": 0},
    }
    report = build_report(summary, ai_quality=None, generated_at=_NOW)

    assert "**Result: PASSING**" in report
    assert "| unit | 29 | 0 | 29 |" in report
    assert "| **total** | **72** | **0** | **72** |" in report


@pytest.mark.unit
def test_report_flags_failures() -> None:
    summary = {
        "unit": {"passed": 29, "failed": 1},
        "integration": {"passed": 43, "failed": 0},
        "e2e": {"passed": 0, "failed": 0},
    }
    report = build_report(summary, ai_quality=None, generated_at=_NOW)

    assert "1 FAILING" in report


_EMPTY_SUMMARY = {
    "unit": {"passed": 1, "failed": 0},
    "integration": {"passed": 0, "failed": 0},
    "e2e": {"passed": 0, "failed": 0},
}


@pytest.mark.unit
def test_report_includes_ai_quality_metrics_when_present() -> None:
    summary = _EMPTY_SUMMARY
    ai_quality = {
        "total_examples": 48,
        "scored_examples": 48,
        "overall_sentiment_accuracy": 1.0,
        "aspect_recall": 1.0,
        "aspect_sentiment_accuracy": 1.0,
        "structured_output_validity_rate": 1.0,
        "total_ai_calls_made": 144,
    }
    report = build_report(summary, ai_quality, generated_at=_NOW)

    assert "100.0%" in report
    assert "48 / 48" in report
    assert "144" in report


@pytest.mark.unit
def test_report_explains_missing_ai_quality_artifact() -> None:
    report = build_report(_EMPTY_SUMMARY, ai_quality=None, generated_at=_NOW)

    assert "No AI-quality eval report found" in report
    assert "scripts/evaluate_ai_analysis.py" in report
