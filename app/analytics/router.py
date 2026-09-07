import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.schemas import AspectsResponse, OverviewResponse
from app.analytics.service import get_overview, get_top_aspects
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
def overview(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OverviewResponse:
    return get_overview(db, business_id)


@router.get("/aspects", response_model=AspectsResponse)
def aspects(
    business_id: uuid.UUID,
    limit: int = 10,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AspectsResponse:
    return get_top_aspects(db, business_id, limit=limit)
