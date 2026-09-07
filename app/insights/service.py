"""Grounded insight generation orchestration (§11: `insights` owns `Insight`; the
second and last module allowed to call the AI client, via `analysis`'s shared wrapper).

No repair-retry loop here (unlike review analysis): the insight schema is a single
free-text field, so a validation failure would only happen from an empty/too-short
string — rare enough that a single dead-letter-and-move-on is the right amount of
complexity, not a second paid call for what forced tool-use rarely gets wrong.
"""

import logging
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.claude_client import call_claude_tool
from app.config import Settings
from app.core.retry import TransientError
from app.insights.evidence import build_insight_evidence
from app.insights.generator import (
    INSIGHT_TOOL_NAME,
    INSIGHT_TOOL_SCHEMA,
    build_insight_prompt,
    deterministic_template_insight,
)
from app.insights.groundedness import check_insight_groundedness
from app.insights.schemas import InsightResult
from app.models.ai_invocation import AIInvocation, AIOperation
from app.models.insight import GenerationMethod, Insight
from app.models.issue import Issue, IssueStatus
from app.models.processing_run import (
    ProcessingRun,
    ProcessingRunJobType,
    ProcessingRunStatus,
    ProcessingRunTrigger,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
CLOSED_STATUSES = (IssueStatus.RESOLVED, IssueStatus.CLOSED, IssueStatus.REJECTED)


def _log_invocation(
    db: Session,
    issue: Issue,
    settings: Settings,
    processing_run_id: uuid.UUID | None,
    *,
    latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    validation_passed: bool,
    error_type: str | None,
) -> AIInvocation:
    invocation = AIInvocation(
        processing_run_id=processing_run_id,
        operation=AIOperation.INSIGHT_SYNTHESIS,
        model=settings.analysis_model,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate_usd=None,
        validation_passed=validation_passed,
        error_type=error_type,
        input_ref=str(issue.id),
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)
    return invocation


def generate_insight(
    db: Session, issue: Issue, settings: Settings, processing_run_id: uuid.UUID | None = None
) -> Insight | None:
    """Returns the newly created Insight, or None if generation was skipped/dead-lettered
    (the issue simply keeps whichever insight it already had, if any — never a bad row).
    """
    evidence = build_insight_evidence(db, issue)

    if not settings.anthropic_api_key:
        text = deterministic_template_insight(evidence)
        insight = Insight(
            issue_id=issue.id, text=text, generation_method=GenerationMethod.DETERMINISTIC_TEMPLATE
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        return insight

    prompt = build_insight_prompt(evidence)
    try:
        response = call_claude_tool(
            prompt, INSIGHT_TOOL_SCHEMA, INSIGHT_TOOL_NAME, settings.analysis_model, settings
        )
    except TransientError as exc:
        _log_invocation(
            db, issue, settings, processing_run_id,
            latency_ms=None, prompt_tokens=None, completion_tokens=None,
            validation_passed=False, error_type="provider_error",
        )
        logger.warning(
            "Insight generation provider error",
            extra={"context": {"issue_id": str(issue.id), "error": str(exc)}},
        )
        return None

    try:
        result = InsightResult.model_validate(response.raw_input)
    except ValidationError:
        _log_invocation(
            db, issue, settings, processing_run_id,
            latency_ms=response.latency_ms, prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            validation_passed=False, error_type="validation_error",
        )
        logger.warning(
            "Insight generation produced invalid output", extra={"context": {"issue_id": str(issue.id)}}
        )
        return None

    check_insight_groundedness(evidence, result.insight_text)  # logs only, never blocks

    invocation = _log_invocation(
        db, issue, settings, processing_run_id,
        latency_ms=response.latency_ms, prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        validation_passed=True, error_type=None,
    )

    insight = Insight(
        issue_id=issue.id,
        text=result.insight_text,
        generation_method=GenerationMethod.LLM_SYNTHESIS,
        ai_invocation_id=invocation.id,
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


def generate_insights_for_business(
    db: Session,
    business_id: uuid.UUID,
    settings: Settings,
    limit: int = 20,
    trigger: ProcessingRunTrigger = ProcessingRunTrigger.MANUAL,
) -> ProcessingRun:
    """Generates (or refreshes) an insight for up to `limit` open issues. `limit`
    defaults low deliberately — insight generation costs a real API call per issue,
    unlike aggregation/trend which are free.
    """
    run = ProcessingRun(
        trigger=trigger,
        job_type=ProcessingRunJobType.INSIGHT,
        status=ProcessingRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    issues = db.execute(
        select(Issue)
        .where(Issue.business_id == business_id, Issue.status.not_in(CLOSED_STATUSES))
        .order_by(Issue.priority_score.desc().nulls_last())
        .limit(limit)
    ).scalars().all()

    succeeded = failed = 0
    for issue in issues:
        insight = generate_insight(db, issue, settings, processing_run_id=run.id)
        if insight is not None:
            succeeded += 1
        else:
            failed += 1

    run.finished_at = datetime.now(UTC)
    run.reviews_in_scope = len(issues)
    run.reviews_succeeded = succeeded
    run.reviews_failed = failed
    run.status = ProcessingRunStatus.COMPLETED_WITH_ERRORS if failed else ProcessingRunStatus.COMPLETED
    db.commit()

    return run
