from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Root tenant concept (§3). Single-tenant in v1, but kept as a real entity so the
    model doesn't need reshaping if multi-tenant is ever pursued (explicitly deferred, §16).
    """

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False, default="restaurant")
