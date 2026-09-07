"""Seeds the single admin user from env vars if the users table is empty.

Deliberate v1 choice (ADR-5, §H): no signup flow, no RBAC — one admin account,
provisioned from ADMIN_EMAIL/ADMIN_PASSWORD at startup, is enough to make the
approval workflow's auth requirement real without building user management.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import Settings
from app.models.user import User

logger = logging.getLogger(__name__)


def seed_admin_user(db: Session, settings: Settings) -> None:
    existing = db.execute(select(User).where(User.email == settings.admin_email)).scalar_one_or_none()
    if existing is not None:
        return

    admin = User(email=settings.admin_email, hashed_password=hash_password(settings.admin_password))
    db.add(admin)
    db.commit()
    logger.info("Seeded admin user", extra={"context": {"email": settings.admin_email}})
