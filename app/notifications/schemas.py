import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    message: str
    read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
