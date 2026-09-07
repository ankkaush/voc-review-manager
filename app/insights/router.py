import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.database import get_db
from app.insights.service import generate_insight, generate_insights_for_business
from app.models.issue import Issue
from app.models.processing_run import ProcessingRunTrigger
from app.models.user import User

router = APIRouter(tags=["insights"])


class InsightOut(BaseModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    text: str
    generation_method: str


class InsightGenerationBatchResponse(BaseModel):
    processing_run_id: str
    status: str
    issues_in_scope: int
    succeeded: int
    failed: int


@router.post("/issues/{issue_id}/insight", response_model=InsightOut)
def generate_issue_insight(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _current_user: User = Depends(get_current_user),
) -> InsightOut:
    """Generates (or refreshes) one issue's insight — one Claude call (or a free
    deterministic-template fallback if no API key is configured, §8 graceful
    degradation). Scoped to a single issue deliberately, so testing this endpoint costs
    at most one real API call, not a batch.
    """
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Issue not found")

    insight = generate_insight(db, issue, settings)
    if insight is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Insight generation failed (provider error or invalid output)"
        )

    return InsightOut(
        id=insight.id,
        issue_id=insight.issue_id,
        text=insight.text,
        generation_method=insight.generation_method,
    )


@router.post("/insights/generate", response_model=InsightGenerationBatchResponse)
def generate_insights_batch(
    business_id: uuid.UUID,
    limit: int = 20,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _current_user: User = Depends(get_current_user),
) -> InsightGenerationBatchResponse:
    """Batch generation, highest-priority issues first. Each issue costs one real API
    call (or is free if no key is configured) — use a small `limit`.
    """
    run = generate_insights_for_business(
        db, business_id, settings, limit=limit, trigger=ProcessingRunTrigger.MANUAL
    )
    return InsightGenerationBatchResponse(
        processing_run_id=str(run.id),
        status=run.status,
        issues_in_scope=run.reviews_in_scope,
        succeeded=run.reviews_succeeded,
        failed=run.reviews_failed,
    )
