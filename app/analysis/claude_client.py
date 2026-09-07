"""Thin wrapper around the Anthropic SDK — the only module allowed to call Claude
directly (§11). `insights/` reuses `call_claude_tool` below rather than talking to the
SDK itself, per §11's "second (and last) module allowed to call the AI client, via
analysis's wrapper, not a new one."

Uses tool-use (forced tool_choice) to get schema-constrained JSON back, rather than
asking for JSON in prose and hoping. The raw tool input is still untrusted until the
caller validates it against its own Pydantic schema — this module's job is only to make
the call and report what happened, not to decide the result is correct.
"""

import time
from dataclasses import dataclass
from typing import Any

import anthropic

from app.config import Settings
from app.core.retry import TransientError, with_transient_retry
from app.taxonomy_seed import TAXONOMY

REVIEW_ANALYSIS_TOOL_NAME = "record_review_analysis"

REVIEW_ANALYSIS_TOOL_SCHEMA = {
    "name": REVIEW_ANALYSIS_TOOL_NAME,
    "description": "Records structured sentiment/topic/aspect analysis for one customer review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral", "mixed"],
                "description": "The review's overall sentiment.",
            },
            "aspects": {
                "type": "array",
                "maxItems": 8,
                "description": "Zero or more specific aspects the review discusses.",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_key": {"type": "string"},
                        "aspect_key": {"type": "string"},
                        "aspect_sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                        "evidence_snippet": {
                            "type": "string",
                            "description": "A short quote from the review text supporting this aspect.",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Only for negative aspects; omit otherwise.",
                        },
                    },
                    "required": ["topic_key", "aspect_key", "aspect_sentiment", "evidence_snippet"],
                },
            },
        },
        "required": ["overall_sentiment", "aspects"],
    },
}


def _build_taxonomy_reference() -> str:
    lines = []
    for topic_key, (topic_label, aspects) in TAXONOMY.items():
        aspect_list = ", ".join(f"{key} ({label})" for key, label in aspects)
        lines.append(f"- {topic_key} ({topic_label}): {aspect_list}")
    return "\n".join(lines)


_TAXONOMY_REFERENCE = _build_taxonomy_reference()


def _build_review_analysis_prompt(review_text: str, repair_error: str | None = None) -> str:
    prompt = f"""You are analyzing a single customer review for a restaurant business.

Classify the review using ONLY the following controlled taxonomy of topics and aspects
— never invent a topic or aspect key outside this list:

{_TAXONOMY_REFERENCE}

For each aspect the review actually discusses, extract: which aspect, its sentiment,
a short verbatim quote from the review as evidence, and a severity (only for negative
aspects). Do not force a classification for vague or non-actionable text — return an
empty aspects list if nothing specific is discussed.

Review text:
\"\"\"{review_text}\"\"\"

Call the {REVIEW_ANALYSIS_TOOL_NAME} tool with your analysis."""

    if repair_error:
        prompt += (
            f"\n\nYour previous response was invalid: {repair_error}\n"
            "Correct it and call the tool again, using only topic_key/aspect_key pairs "
            "from the taxonomy above."
        )
    return prompt


@dataclass
class ClaudeToolResponse:
    raw_input: dict[str, Any]
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def _get_client(settings: Settings) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.analysis_timeout_seconds)


@with_transient_retry
def _invoke(
    client: anthropic.Anthropic, model: str, prompt: str, tool_schema: dict, tool_name: str
) -> tuple[anthropic.types.Message, int]:
    start = time.monotonic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": prompt}],
        )
    except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
        raise TransientError(str(exc)) from exc
    except anthropic.InternalServerError as exc:
        raise TransientError(str(exc)) from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    return response, latency_ms


def call_claude_tool(
    prompt: str, tool_schema: dict, tool_name: str, model: str, settings: Settings
) -> ClaudeToolResponse:
    """Generic forced-tool-use call, shared by review analysis and insight synthesis.

    Raises TransientError (after the retry budget in `with_transient_retry` is
    exhausted) for provider-side failures. Never raises for a malformed *response* —
    that's a validation concern for the caller's own Pydantic schema.
    """
    client = _get_client(settings)
    response, latency_ms = _invoke(client, model, prompt, tool_schema, tool_name)

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    raw_input = tool_use_block.input if tool_use_block is not None else {}

    return ClaudeToolResponse(
        raw_input=raw_input,
        model=response.model,
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        latency_ms=latency_ms,
    )


def analyze_review_text(
    review_text: str, settings: Settings, repair_error: str | None = None
) -> ClaudeToolResponse:
    prompt = _build_review_analysis_prompt(review_text, repair_error)
    return call_claude_tool(
        prompt, REVIEW_ANALYSIS_TOOL_SCHEMA, REVIEW_ANALYSIS_TOOL_NAME, settings.analysis_model, settings
    )
