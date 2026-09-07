"""Builds the structured evidence object an Insight is generated from (§5, Open
Question 4 resolved): deterministic facts only, computed before any LLM call — the
model never sees raw counts it could misreport, only this pre-computed snapshot.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.issues.trend import TrendResult, compute_trend
from app.models.issue import EvidenceType, Issue, IssueEvidence
from app.models.location import Location
from app.models.review import Review
from app.models.taxonomy import Aspect, Topic

MAX_REVIEW_SNIPPETS_IN_PROMPT = 5


@dataclass
class InsightEvidence:
    topic_label: str
    aspect_label: str
    location_name: str | None
    severity: str | None
    current_period_start: date | None
    current_period_end: date | None
    current_count: int
    baseline_period_start: date | None
    baseline_period_end: date | None
    baseline_count: int
    change_pct: float | None
    direction: str
    representative_review_texts: list[str] = field(default_factory=list)


def build_insight_evidence(db: Session, issue: Issue) -> InsightEvidence:
    topic = db.get(Topic, issue.topic_id)
    aspect = db.get(Aspect, issue.aspect_id)
    location = db.get(Location, issue.location_id) if issue.location_id else None

    trend: TrendResult = compute_trend(db, issue)

    review_ids = [
        e.review_id
        for e in db.execute(
            select(IssueEvidence).where(
                IssueEvidence.issue_id == issue.id,
                IssueEvidence.evidence_type == EvidenceType.REVIEW_CITATION,
            )
        ).scalars()
    ][:MAX_REVIEW_SNIPPETS_IN_PROMPT]

    review_texts = []
    if review_ids:
        reviews = db.execute(select(Review).where(Review.id.in_(review_ids))).scalars().all()
        review_texts = [r.text for r in reviews]

    return InsightEvidence(
        topic_label=topic.label,
        aspect_label=aspect.label,
        location_name=location.name if location else None,
        severity=issue.severity,
        current_period_start=trend.current_period_start,
        current_period_end=trend.current_period_end,
        current_count=trend.current_negative_count,
        baseline_period_start=trend.baseline_period_start,
        baseline_period_end=trend.baseline_period_end,
        baseline_count=trend.baseline_negative_count,
        change_pct=trend.change_pct,
        direction=trend.direction,
        representative_review_texts=review_texts,
    )
