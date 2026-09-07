import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.actions.router import router as actions_router
from app.aggregation.router import router as aggregation_router
from app.analysis.router import router as analysis_router
from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.auth.seed import seed_admin_user
from app.businesses.router import router as businesses_router
from app.config import get_settings
from app.database import SessionLocal
from app.ingestion.router import router as reviews_router
from app.insights.router import router as insights_router
from app.issues.router import router as issues_router
from app.logging_config import configure_logging
from app.notifications.router import router as notifications_router
from app.observability.router import router as system_health_router
from app.observability.sentry import init_sentry
from app.rate_limit import limiter
from app.taxonomy_seed import seed_taxonomy

settings = get_settings()
configure_logging(settings.log_level)
init_sentry(settings)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db = SessionLocal()
    try:
        seed_admin_user(db, settings)
        seed_taxonomy(db)
    finally:
        db.close()
    logger.info("Application startup complete", extra={"context": {"env": settings.env}})
    yield


app = FastAPI(title="Review Manager / Voice of Customer API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(system_health_router)
app.include_router(reviews_router)
app.include_router(analysis_router)
app.include_router(aggregation_router)
app.include_router(issues_router)
app.include_router(insights_router)
app.include_router(actions_router)
app.include_router(analytics_router)
app.include_router(businesses_router)
app.include_router(notifications_router)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
