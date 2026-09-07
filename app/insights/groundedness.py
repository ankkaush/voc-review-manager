"""Secondary safety net only (§5 point 4 / ADR-11) — NOT the primary factual guarantee.

The primary guarantee is architectural: the dashboard renders numbers from
`Issue.trend_change_pct` / `AggregatePeriodMetric` fields directly, never parsed out of
LLM prose. This check just flags (logs) when generated text mentions a number that
doesn't match the evidence it was given — useful for catching prompt-following
failures, not required for the numbers shown to a user to be correct.
"""

import logging
import re

from app.insights.evidence import InsightEvidence

logger = logging.getLogger(__name__)

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def check_insight_groundedness(evidence: InsightEvidence, insight_text: str) -> bool:
    """Returns True if every number mentioned in insight_text matches some evidence
    value (within rounding tolerance). Never raises; only logs on mismatch.

    "Evidence" includes numbers appearing in the representative review texts, not just
    the aggregate count/percentage fields — the model was given those review quotes as
    part of its evidence object (§insights/generator.py), so a number it accurately
    cites from a review (e.g. "waited 45 minutes") is grounded, not invented.
    """
    expected_numbers = {evidence.current_count, evidence.baseline_count}
    if evidence.change_pct is not None:
        expected_numbers.add(round(evidence.change_pct))
        expected_numbers.add(round(abs(evidence.change_pct)))
    for review_text in evidence.representative_review_texts:
        for m in _NUMBER_PATTERN.findall(review_text):
            if float(m) == int(float(m)):
                expected_numbers.add(int(float(m)))

    mentioned = [int(float(m)) for m in _NUMBER_PATTERN.findall(insight_text) if float(m) == int(float(m))]

    ungrounded = [n for n in mentioned if not any(abs(n - e) <= 1 for e in expected_numbers)]
    if ungrounded:
        logger.warning(
            "Insight text mentions numbers not present in its evidence object",
            extra={"context": {"ungrounded_numbers": ungrounded, "insight_text": insight_text}},
        )
        return False
    return True
