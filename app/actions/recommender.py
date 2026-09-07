"""Grounded action-recommendation prompt + tool schema (§6/§7 of the kickoff spec:
"AI may recommend. It should not autonomously execute consequential business
decisions."). Reuses the exact same `InsightEvidence` snapshot as `insights/` — the
recommendation and the insight are two different syntheses of one evidence object, not
two independent AI judgments of the underlying numbers.
"""

from app.insights.evidence import InsightEvidence

ACTION_RECOMMENDATION_TOOL_NAME = "record_action_recommendation"

ACTION_RECOMMENDATION_TOOL_SCHEMA = {
    "name": ACTION_RECOMMENDATION_TOOL_NAME,
    "description": "Records a recommended operational action addressing a recurring customer-feedback issue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommended_action": {
                "type": "string",
                "description": (
                    "1-2 sentences describing a concrete, specific operational action "
                    "management could take. Base it only on the evidence given — do not "
                    "invent facts, and propose a response rather than restating the issue."
                ),
            }
        },
        "required": ["recommended_action"],
    },
}


def build_action_recommendation_prompt(evidence: InsightEvidence) -> str:
    location_phrase = f" at {evidence.location_name}" if evidence.location_name else " across all locations"

    lines = [
        "You are recommending a concrete operational action for a restaurant business "
        "in response to a recurring customer-feedback issue. A human manager will "
        "review and decide whether to approve this recommendation — you are not "
        "executing anything.",
        "",
        "Use ONLY the evidence below. Do not invent facts not given here.",
        "",
        f"Issue: {evidence.aspect_label} ({evidence.topic_label}){location_phrase}",
        f"Severity: {evidence.severity or 'unrated'}",
        f"Current period negative mentions: {evidence.current_count}",
        f"Trend: {evidence.direction}"
        + (f" ({evidence.change_pct:.0f}% vs. baseline)" if evidence.change_pct is not None else ""),
    ]

    if evidence.representative_review_texts:
        lines.append("")
        lines.append("Representative customer feedback:")
        for text in evidence.representative_review_texts:
            lines.append(f'- "{text}"')

    lines.append("")
    lines.append(
        f"Recommend one concrete, specific operational action. Call the "
        f"{ACTION_RECOMMENDATION_TOOL_NAME} tool with your recommendation."
    )

    return "\n".join(lines)


def deterministic_template_recommendation(evidence: InsightEvidence) -> str:
    """Fallback when no API key is configured (§8 graceful degradation)."""
    location_phrase = f" at {evidence.location_name}" if evidence.location_name else ""
    return (
        f"Review current operations related to {evidence.aspect_label.lower()}{location_phrase} "
        f"and address the root cause of the {evidence.current_count} negative mentions in the "
        f"current period."
    )
