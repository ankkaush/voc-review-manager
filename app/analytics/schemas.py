import uuid

from pydantic import BaseModel


class OverviewResponse(BaseModel):
    """Business analytics (§9): "what are customers saying" — computed directly from
    Review/ReviewAnalysis, never from a processing-run/technical table. Deliberately
    separate from /system-health, which answers "is the system working" instead.
    """

    business_id: uuid.UUID
    review_count: int
    ingestion_status_counts: dict[str, int]
    analysis_status_counts: dict[str, int]
    rating_distribution: dict[str, int]
    sentiment_distribution: dict[str, int]
    language_distribution: dict[str, int]


class AspectSummary(BaseModel):
    topic_key: str
    topic_label: str
    aspect_key: str
    aspect_label: str
    mention_count: int
    negative_count: int
    positive_count: int


class AspectsResponse(BaseModel):
    top_negative: list[AspectSummary]
    top_positive: list[AspectSummary]
