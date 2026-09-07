from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analysis.service import analyze_pending_reviews
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.database import get_db
from app.models.processing_run import ProcessingRunTrigger
from app.models.user import User

router = APIRouter(prefix="/analysis", tags=["analysis"])


class AnalysisRunResponse(BaseModel):
    processing_run_id: str
    status: str
    reviews_in_scope: int
    reviews_succeeded: int
    reviews_failed: int


@router.post("/run", response_model=AnalysisRunResponse)
def run_analysis(
    limit: int = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _current_user: User = Depends(get_current_user),
) -> AnalysisRunResponse:
    """Manually triggers analysis of pending reviews. A stand-in for Phase 10's
    scheduled cron job — the underlying `analyze_pending_reviews` call is identical
    either way, only the trigger differs.
    """
    run = analyze_pending_reviews(db, settings, limit=limit, trigger=ProcessingRunTrigger.MANUAL)
    return AnalysisRunResponse(
        processing_run_id=str(run.id),
        status=run.status,
        reviews_in_scope=run.reviews_in_scope,
        reviews_succeeded=run.reviews_succeeded,
        reviews_failed=run.reviews_failed,
    )
