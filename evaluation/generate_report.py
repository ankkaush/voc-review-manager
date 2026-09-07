"""Generates evaluation/EVAL_REPORT.md (Phase 11 DoD: "eval report committed/
documented with accuracy numbers you can explain and defend").

Runs the deterministic pytest suite per marker (free — no API calls) and reads the
already-committed AI-quality eval artifact (data/synthetic/eval_report.json) without
re-running it (that would spend real API budget — see evaluation/ai_quality.py).

Usage:
    python evaluation/generate_report.py
"""

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.ai_quality import load_latest_report  # noqa: E402
from evaluation.report import build_report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORT_OUTPUT = Path(__file__).resolve().parent / "EVAL_REPORT.md"
_SUMMARY_RE = re.compile(r"(\d+) passed|(\d+) failed")


def _run_marker(marker: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", marker],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    passed = failed = 0
    for match in _SUMMARY_RE.finditer(result.stdout):
        if match.group(1):
            passed = int(match.group(1))
        elif match.group(2):
            failed = int(match.group(2))
    return {"passed": passed, "failed": failed}


def main() -> None:
    test_summary = {marker: _run_marker(marker) for marker in ("unit", "integration", "e2e")}
    ai_quality = load_latest_report()

    report_text = build_report(test_summary, ai_quality, datetime.now(UTC))
    REPORT_OUTPUT.write_text(report_text)
    print(f"Report written to {REPORT_OUTPUT}")
    print(report_text)


if __name__ == "__main__":
    main()
