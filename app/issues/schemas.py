import uuid
from datetime import date, datetime

from pydantic import BaseModel


class IssueOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    location_id: uuid.UUID | None
    topic_id: uuid.UUID
    aspect_id: uuid.UUID
    title: str
    description: str
    status: str
    severity: str | None
    priority_score: float | None
    priority_score_breakdown: dict | None
    trend_direction: str | None
    trend_change_pct: float | None
    first_detected_at: datetime
    last_updated_at: datetime

    model_config = {"from_attributes": True}


class MetricEvidenceItem(BaseModel):
    aggregate_period_metric_id: uuid.UUID
    period_start: date
    period_end: date
    mention_count: int
    negative_count: int
    positive_count: int
    neutral_count: int
    avg_rating: float | None
    note: str | None


class ReviewCitationItem(BaseModel):
    review_id: uuid.UUID
    text: str
    rating: int | None
    submitted_at: datetime


class InsightItem(BaseModel):
    id: uuid.UUID
    text: str
    generation_method: str
    created_at: datetime


class DismissIssueRequest(BaseModel):
    reason: str | None = None


class WorkflowEventItem(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    from_state: str | None
    to_state: str
    actor: str
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IssueEvidenceResponse(BaseModel):
    """The provenance chain for one issue (§5): every number traceable to the specific
    weekly metrics and representative reviews behind it — never an unsupported claim.

    `latest_insight` is explanatory prose (§Open-Question-4 resolved): it is displayed
    alongside the deterministic numbers above, never as their source. A dashboard must
    render `issue.trend_change_pct` etc. directly, not parse a number out of this text.
    """

    issue: IssueOut
    metrics: list[MetricEvidenceItem]
    review_citations: list[ReviewCitationItem]
    latest_insight: InsightItem | None
