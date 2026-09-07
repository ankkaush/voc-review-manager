"""Read-only discovery for Business/Location (§3: created only via the dataset seed
script in v1, no create/update API — this is just enough for the dashboard to know
what exists, not a full CRUD surface).
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.business import Business
from app.models.location import Location
from app.models.user import User

router = APIRouter(prefix="/businesses", tags=["businesses"])


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    industry: str

    model_config = {"from_attributes": True}


class LocationOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    city: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BusinessOut])
def list_businesses(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Business]:
    return list(db.execute(select(Business)).scalars().all())


@router.get("/{business_id}/locations", response_model=list[LocationOut])
def list_locations(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Location]:
    return list(db.execute(select(Location).where(Location.business_id == business_id)).scalars().all())
