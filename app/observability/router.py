from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.processing_run import ProcessingRun
from app.models.user import User

router = APIRouter(prefix="/system-health", tags=["system-health"])


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Technical observability read: recent processing runs. Kept behind auth like every
    other non-public endpoint, and deliberately separate from any business/VoC route.
    """
    query = select(ProcessingRun).order_by(ProcessingRun.started_at.desc()).limit(50)
    runs = db.execute(query).scalars().all()
    return [
        {
            "id": str(run.id),
            "trigger": run.trigger,
            "job_type": run.job_type,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "reviews_in_scope": run.reviews_in_scope,
            "reviews_succeeded": run.reviews_succeeded,
            "reviews_failed": run.reviews_failed,
        }
        for run in runs
    ]
