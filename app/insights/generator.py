"""Grounded insight prompt + tool schema (§5, §D). The LLM only ever sees the
pre-computed `InsightEvidence` snapshot — it synthesizes prose, it does not compute or
invent any number.
"""

from app.insights.evidence import InsightEvidence

INSIGHT_TOOL_NAME = "record_issue_insight"

INSIGHT_TOOL_SCHEMA = {
    "name": INSIGHT_TOOL_NAME,
    "description": "Records a grounded, concise management insight for a recurring customer-feedback issue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "insight_text": {
                "type": "string",
                "description": (
                    "1-3 sentences explaining the evidence and its likely business meaning. "
                    "Reference ONLY numbers explicitly given in the evidence below — never "
                    "invent, round differently, or restate a figure not present verbatim."
                ),
            }
        },
        "required": ["insight_text"],
    },
}


def _format_period(start, end) -> str:
    if start is None or end is None:
        return "unknown period"
    return f"{start.isoformat()} to {end.isoformat()}"


def build_insight_prompt(evidence: InsightEvidence) -> str:
    location_phrase = f" at {evidence.location_name}" if evidence.location_name else " across all locations"

    lines = [
        "You are writing a concise, grounded management insight about a recurring "
        "customer-feedback issue for a restaurant business.",
        "",
        "Use ONLY the evidence below. Do not invent, estimate, or restate any number "
        "that is not given here verbatim.",
        "",
        f"Issue: {evidence.aspect_label} ({evidence.topic_label}){location_phrase}",
        f"Severity: {evidence.severity or 'unrated'}",
        f"Current period ({_format_period(evidence.current_period_start, evidence.current_period_end)}): "
        f"{evidence.current_count} negative mentions",
    ]

    if evidence.baseline_count or evidence.baseline_period_start:
        lines.append(
            f"Previous baseline period "
            f"({_format_period(evidence.baseline_period_start, evidence.baseline_period_end)}): "
            f"{evidence.baseline_count} negative mentions"
        )
    if evidence.change_pct is not None:
        lines.append(f"Change vs. baseline: {evidence.change_pct:.0f}%")
    lines.append(f"Trend classification: {evidence.direction}")

    if evidence.representative_review_texts:
        lines.append("")
        lines.append("Representative customer feedback:")
        for text in evidence.representative_review_texts:
            lines.append(f'- "{text}"')

    lines.append("")
    lines.append(
        f"Write a 1-3 sentence grounded insight explaining what this evidence shows and "
        f"its likely business meaning. Call the {INSIGHT_TOOL_NAME} tool with your insight."
    )

    return "\n".join(lines)


def deterministic_template_insight(evidence: InsightEvidence) -> str:
    """Fallback used when no API key is configured (§8: graceful degradation, not a
    blocked feature) — still fully grounded, just template prose instead of LLM prose.
    """
    location_phrase = f" at {evidence.location_name}" if evidence.location_name else " across all locations"
    trend_phrase = {
        "emerging": "has increased notably",
        "declining": "has decreased notably",
        "stable": "has stayed roughly stable",
        "new": "is newly observed, with no prior baseline yet",
        "insufficient_data": "does not yet have enough data for a trend comparison",
    }.get(evidence.direction, "has been observed")

    change_clause = f" ({evidence.change_pct:.0f}% vs. baseline)" if evidence.change_pct is not None else ""

    return (
        f"{evidence.aspect_label} complaints{location_phrase} {trend_phrase}{change_clause}, "
        f"with {evidence.current_count} negative mentions in the current period."
    )
