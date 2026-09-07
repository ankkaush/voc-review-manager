import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class ActionRecommendationResult(BaseModel):
    """Structured-output contract for the AI action-recommendation call."""

    recommended_action: str = Field(min_length=10, max_length=600)


class ActionOut(BaseModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    type: str
    recommended_text: str
    status: str
    assigned_to: str | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ApproveActionRequest(BaseModel):
    decision_note: str | None = None
    modified_text: str | None = None


class RejectActionRequest(BaseModel):
    decision_note: str | None = None


class OutcomeOut(BaseModel):
    """Deterministic before/after verdict (§7): every field here is directly computed
    from AggregatePeriodMetric, never an LLM claim.
    """

    id: uuid.UUID
    action_id: uuid.UUID
    before_period_start: date
    before_period_end: date
    before_negative_count: int
    after_period_start: date | None
    after_period_end: date | None
    after_negative_count: int | None
    delta_pct: float | None
    interpretation: str

    model_config = {"from_attributes": True}
