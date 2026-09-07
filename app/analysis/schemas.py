"""Structured-output contract for Claude's review analysis (§6/§D).

This is the trust boundary the whole AI layer is built around: raw model output is
never used until it parses into these Pydantic models, including a taxonomy-membership
check — an LLM inventing a topic/aspect outside the seeded controlled vocabulary is a
validation failure, not a new category.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.taxonomy_seed import TAXONOMY

VALID_TOPIC_KEYS: set[str] = set(TAXONOMY.keys())
VALID_TOPIC_ASPECT_PAIRS: set[tuple[str, str]] = {
    (topic_key, aspect_key)
    for topic_key, (_, aspects) in TAXONOMY.items()
    for aspect_key, _ in aspects
}

Sentiment = Literal["positive", "negative", "neutral"]
OverallSentiment = Literal["positive", "negative", "neutral", "mixed"]
Severity = Literal["low", "medium", "high"]


class AspectResult(BaseModel):
    topic_key: str
    aspect_key: str
    aspect_sentiment: Sentiment
    evidence_snippet: str = Field(min_length=1, max_length=500)
    severity: Severity | None = None

    @model_validator(mode="after")
    def _validate_taxonomy_membership(self) -> "AspectResult":
        if (self.topic_key, self.aspect_key) not in VALID_TOPIC_ASPECT_PAIRS:
            raise ValueError(
                f"Unknown topic/aspect pair: ({self.topic_key!r}, {self.aspect_key!r}) "
                "is not in the seeded taxonomy"
            )
        return self


class ReviewAnalysisResult(BaseModel):
    overall_sentiment: OverallSentiment
    aspects: list[AspectResult] = Field(default_factory=list, max_length=8)
