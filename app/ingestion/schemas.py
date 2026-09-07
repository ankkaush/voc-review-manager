import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.review import ReviewSource


class ReviewIn(BaseModel):
    business_id: uuid.UUID
    location_id: uuid.UUID
    source: ReviewSource = ReviewSource.SEED
    source_review_id: str | None = Field(default=None, max_length=128)
    rating: int | None = Field(default=None, ge=1, le=5)
    text: str = Field(min_length=1, max_length=5000)
    reviewer_display_name: str | None = Field(default=None, max_length=255)
    submitted_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    location_id: uuid.UUID
    source: ReviewSource
    source_review_id: str | None
    rating: int | None
    text: str
    detected_language: str | None
    reviewer_display_name: str | None
    submitted_at: datetime
    ingested_at: datetime
    ingestion_status: str
    analysis_status: str | None

    model_config = {"from_attributes": True}


class ReviewIngestResult(BaseModel):
    index: int
    ingestion_status: Literal["accepted", "duplicate", "rejected"]
    review_id: uuid.UUID | None = None
    detected_language: str | None = None
    error: str | None = None


class BatchIngestResponse(BaseModel):
    processing_run_id: uuid.UUID
    total: int
    accepted: int
    duplicate: int
    rejected: int
    results: list[ReviewIngestResult]
