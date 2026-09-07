import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.aggregation.service import compute_weekly_aggregates
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.processing_run import ProcessingRunTrigger
from app.models.user import User

router = APIRouter(prefix="/aggregation", tags=["aggregation"])


class AggregationRunResponse(BaseModel):
    processing_run_id: str
    status: str
    reviews_in_scope: int


@router.post("/run", response_model=AggregationRunResponse)
def run_aggregation(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AggregationRunResponse:
    """Recomputes weekly AggregatePeriodMetric rows from ReviewAspect (§11). A stand-in
    for Phase 10's scheduled job; safe to re-run at any time (upserts by natural key).
    """
    run = compute_weekly_aggregates(db, business_id, trigger=ProcessingRunTrigger.MANUAL)
    return AggregationRunResponse(
        processing_run_id=str(run.id), status=run.status, reviews_in_scope=run.reviews_in_scope
    )
