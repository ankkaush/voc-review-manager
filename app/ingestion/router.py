import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.ingestion.schemas import BatchIngestResponse, ReviewIn, ReviewOut
from app.ingestion.service import ingest_batch, ingest_single_item
from app.models.processing_run import ProcessingRunTrigger
from app.models.review import Review
from app.models.user import User

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewIn,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Review:
    result = ingest_single_item(db, payload.model_dump(mode="json"), index=0)

    if result.ingestion_status == "rejected":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result.error)
    if result.ingestion_status == "duplicate":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Duplicate of review {result.review_id}")

    return db.get(Review, result.review_id)


@router.post("/batch", response_model=BatchIngestResponse)
def create_reviews_batch(
    payload: list[dict[str, Any]],
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> BatchIngestResponse:
    """Accepts raw dicts, not `list[ReviewIn]` — validating each item individually inside
    `ingest_batch` (rather than via FastAPI's automatic body validation) is what gives
    failure isolation: one malformed item must not 422 the entire batch.
    """
    return ingest_batch(db, payload, trigger=ProcessingRunTrigger.MANUAL)


@router.get("", response_model=list[ReviewOut])
def list_reviews(
    business_id: uuid.UUID,
    location_id: uuid.UUID | None = None,
    ingestion_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Review]:
    query = select(Review).where(Review.business_id == business_id)
    if location_id is not None:
        query = query.where(Review.location_id == location_id)
    if ingestion_status is not None:
        query = query.where(Review.ingestion_status == ingestion_status)

    query = query.order_by(Review.submitted_at.desc()).offset(offset).limit(min(limit, 200))
    return list(db.execute(query).scalars().all())
