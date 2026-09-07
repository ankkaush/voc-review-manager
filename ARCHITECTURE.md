> **This is the deep technical reference** — the original architecture package this system was
> designed against, kept intact as-written (including its phase-by-phase build plan, ADR log, and
> resolved open-questions log) because that reasoning is still accurate and worth preserving. For
> a scannable overview of what's actually built, tested, and verified today, see
> [README.md](README.md) instead — this document predates implementation and is not the place to
> check current status.

# Phase 0 Architecture Package — Review Manager / Voice of Customer

Status: **FINAL — APPROVED FOR IMPLEMENTATION** (as of the initial design review). All six open
questions from the prior draft are resolved (§15) and the corrections below (Review status split,
groundedness layering, background-processing terminology, Phase 8 demotion) are incorporated. This
section describes the state of the *plan* at design time, before Phase 1 began — see README.md for
what has since been built.

---

## 1. Architecture Overview

This system converts unstructured customer reviews into prioritized, evidence-backed business
issues and human-approved operational actions, for a synthetic multi-location restaurant group.

Core design commitments (now locked per mentor review):

- AI performs **interpretation and judgment** (sentiment, topic/aspect classification, grounded
  synthesis). Deterministic code performs **control and execution** (persistence, aggregation,
  math, workflow transitions, retries, scheduling, auth).
- Every business conclusion shown to a user is **traceable to the individual reviews and
  computations that produced it** — no unsupported AI claims.
- Statistics for trend/emerging-issue detection are **transparent formulas**, not ML/black-box
  anomaly detection.
- Consequential actions (operational tasks, public review responses) require **explicit human
  approval** before taking effect.
- No agents, no task queue infrastructure, no multi-provider abstraction, no RBAC — each omitted
  deliberately because the project doesn't have the scale/complexity problem those solve.

---

## 2. System Architecture

```
 ┌────────────────────────────┐
 │   Next.js Dashboard         │   Business/VoC views + System Health view
 │  (React, Recharts/Tremor)   │   Approval actions (issue/action approve-reject)
 └──────────────┬───────────────┘
                │ HTTPS REST (session/JWT)
                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                      FastAPI Backend                          │
 │  Modules (see §11 for boundaries):                            │
 │   ingestion │ analysis │ aggregation │ issues │ insights       │
 │   actions │ workflow │ auth │ observability │ evaluation       │
 └───────┬───────────────────────────────┬────────────────────────┘
         │ sync (request/response)       │ triggers
         ▼                               ▼
 ┌────────────────────┐        ┌────────────────────────────┐
 │  PostgreSQL          │◀──────│  Scheduled Jobs (cron)      │
 │  (SQLAlchemy+Alembic)│        │  - ingest batch              │
 │                       │        │  - run pending analysis      │
 │  Source-of-truth      │        │  - weekly aggregation/trend   │
 │  domain tables         │        │  - weekly VoC summary          │
 └──────────┬────────────┘        └───────────┬────────────────────┘
            │                                   │ async, background job
            │                                   ▼
            │                        ┌────────────────────────────┐
            │                        │  AI Analysis Layer          │
            │◀───────validated───────│  Claude (structured output) │
            │        results         │  Pydantic-validated          │
            │                        │  retries/backoff/timeout     │
            │                        └────────────────────────────┘
            │
            ▼
   Cross-cutting concerns (apply at every layer above):
   auth · input validation · idempotency · retries/backoff · timeouts ·
   structured error handling · audit logging (WorkflowEvent) ·
   observability (ProcessingRun/AIInvocation + Sentry + JSON logs) ·
   evaluation hooks · secrets via env vars
```

**Sync vs async — no message queue, database-backed pending work instead:**
- **Synchronous (request/response):** single-review ingestion (`POST /reviews`), all read/analytics
  endpoints, approval actions (`POST /issues/{id}/approve` etc.) — these must respond immediately
  because a human or API caller is waiting.
- **Background/scheduled (not queue-based):** AI analysis, weekly aggregation, trend detection,
  insight/recommendation generation, and outcome monitoring do not run inline with a request. The
  correct description of this design is **database-backed pending work, picked up by scheduled
  jobs** — there is no message broker or task queue anywhere in the system. Concretely:

  ```
  Batch ingestion → persist reviews → mark analysis_status = pending → return ingestion response
                                                    ↓
                          Scheduled/cron job queries WHERE analysis_status IN ('pending','pending_retry')
                                                    ↓
                                    Processes AI analysis per review, updates analysis_status
  ```

  `POST /reviews` and `POST /reviews/batch` both persist synchronously and return immediately;
  `analysis_status` starts at `pending` and is advanced later by the next scheduled analysis run.
  No queue, no broker, no async task runner — Postgres itself is the work list, and a cron-triggered
  job process reading/writing it directly is sufficient at this volume (hundreds–low thousands of
  reviews per run). This is a deliberate scale-appropriate choice, not an oversight (see ADR-3).

---

## 3. Domain Model + Relationships

Entities are grouped into **source-of-truth** (human/external input, never derived) and **derived**
(computed by deterministic code or AI, always regenerable from source-of-truth + code).

### Source-of-truth entities

**Business** — id, name, industry (fixed: "restaurant" for v1). Root tenant concept, kept even
though v1 is single-tenant, so the model doesn't need reshaping later.

**Location** — id, business_id FK, name, city/region, opened_date. Reviews and issues are scoped
per-location; aggregations roll up across locations.

**Review** — id, business_id FK, location_id FK, source (enum: csv/json/seed/mock_api), source_review_id
(nullable), content_hash (for dedup when no stable external id), rating (1–5, nullable), text,
detected_language, reviewer_display_name (pseudonymous, no PII), submitted_at, ingested_at.
**Unique constraint** on `(business_id, source, source_review_id)` and a secondary unique
constraint on `(business_id, location_id, content_hash)` for idempotency when no external id exists.
This is the immutable input record — text/rating/metadata are never mutated after ingestion.

Lifecycle is tracked with **two separate status fields**, not one, because ingestion and AI
analysis are distinct concerns that can fail independently (a review can be successfully ingested
and still be stuck `pending_retry` in analysis):

- `ingestion_status`: `accepted` / `duplicate` / `rejected` — set once, at ingestion time, and
  never changed afterward.
- `analysis_status`: `pending` / `processing` / `analyzed` / `pending_retry` / `failed` — owned by
  the `analysis/` module, advanced by the background analysis job (§8/§13 Phase 3).

Example: `ingestion_status = accepted, analysis_status = pending_retry` describes a review that was
correctly stored but has not yet been successfully interpreted by the AI layer — a normal,
expected, and fully recoverable state, not an error condition on the review itself.

**WorkflowEvent (Audit log)** — id, entity_type (issue/action/review), entity_id, from_state,
to_state, actor (system/user id), reason/note, created_at. Append-only. Source-of-truth for "who
did what when" — never derived, never deleted.

### Derived entities (AI + deterministic)

**Taxonomy: Topic / Aspect** — small seeded reference tables (topic: food, service, staff, price,
cleanliness, delivery, wait_time...; aspect: food_quality, wait_time, staff_friendliness,
price_value...). Static/seed data, not user-editable in v1. Gives classification a controlled
vocabulary instead of free-form AI-invented labels — critical for both explainability and for
aggregation to work at all.

**ReviewAnalysis** — id, review_id FK (1:1), overall_sentiment (pos/neg/neutral/mixed),
language_confidence, model, prompt_version, created_at, `raw_ai_response_id` FK →
AIInvocation (provenance link, see §5). Source of AI-derived, per-review interpretation.

**ReviewAspect** — id, review_analysis_id FK, topic_id FK, aspect_id FK, aspect_sentiment
(pos/neg/neutral), evidence_snippet (short quoted span from the review text supporting this
classification), severity (low/medium/high, nullable — only meaningful for negative aspects).
One review can produce multiple rows here (multi-aspect reviews). This table is the atomic unit
that all aggregation/issue-detection is built on.

**AggregatePeriodMetric** — id, business_id, location_id (nullable = all locations), topic_id,
aspect_id, period_start, period_end (weekly buckets), mention_count, negative_count,
positive_count, avg_rating_of_mentioning_reviews. **Fully deterministic, regenerable** from
ReviewAspect by a SQL aggregation job — never hand-edited, never AI-touched. This is the
provenance backbone for every trend/issue claim.

**Issue** — id, business_id, location_id (nullable), topic_id, aspect_id, title, description,
status (identified → reviewed → recommended → awaiting_approval → approved/rejected →
action_created → resolved → monitoring → closed), severity, priority_score,
priority_score_breakdown (JSON: the individual factor values that produced the score — see §4),
first_detected_at, last_updated_at. A recurring pattern promoted to a trackable business problem.

**IssueEvidence** — id, issue_id FK, aggregate_period_metric_id FK (nullable), review_id FK
(nullable), evidence_type (metric / review_citation), note. **This table is the provenance join**
between an Issue/Insight and the concrete numbers/reviews behind it (detailed in §5). Many rows per
issue: some point at the aggregate metrics used to compute trend/frequency, others point at
specific representative reviews a human or the LLM cited.

**Insight** — id, issue_id FK, text (LLM-synthesized, grounded), generation_method
(deterministic_template / llm_synthesis), ai_invocation_id FK (nullable — null if
deterministic-template-only), created_at. The human-readable narrative; always generated *from*
IssueEvidence, never independently.

**Action** — id, issue_id FK, type (operational_task / public_review_response),
recommended_text, ai_invocation_id FK (origin of the recommendation), status (same workflow
enum as Issue, action-scoped), assigned_to (free text/email, no real user system needed),
created_at, resolved_at.

**ActionApproval** — id, action_id FK, decision (approved/rejected/modified), approver,
decision_note, modified_text (nullable, if the human edited the AI draft before approving),
decided_at. Kept separate from Action so an action's approval history is auditable even if
re-submitted.

**Outcome** — id, action_id FK, aggregate_period_metric_id_before FK, aggregate_period_metric_id_after
FK, delta_pct, interpretation ("improved"/"worsened"/"no significant change"), computed_at.
Deterministic comparison of the issue's metric before vs. after the action's resolution date.

### Technical/observability entities (separate namespace, §8)

**ProcessingRun** — id, trigger (cron/manual), job_type (ingest/analyze/aggregate/trend/summary),
started_at, finished_at, status, reviews_in_scope, reviews_succeeded, reviews_failed.

**AIInvocation** — id, processing_run_id FK (nullable), operation (sentiment_extraction /
insight_synthesis / action_recommendation), model, prompt_version, latency_ms, prompt_tokens,
completion_tokens, cost_estimate_usd, validation_passed (bool), error_type (nullable),
input_ref (review_id or issue_id), created_at. Every LLM call, no exceptions, is logged here —
this table *is* the LLM observability system (§ mentor point 16/8).

### Relationships summary

```
Business 1──* Location 1──* Review 1──1 ReviewAnalysis 1──* ReviewAspect
                                │                                 │
                                │                          (feeds aggregation)
                                ▼                                 ▼
                          AIInvocation ◀───────────────  AggregatePeriodMetric
                                ▲                                 │
                                │                          (feeds detection)
                                │                                 ▼
                          Insight ◀── IssueEvidence ──▶ Issue ──▶ Action ──▶ ActionApproval
                                                                     │
                                                                     ▼
                                                                  Outcome
                                                              (references before/after
                                                               AggregatePeriodMetric)

WorkflowEvent: append-only audit, FK'd loosely to (entity_type, entity_id) for Issue/Action/Review
ProcessingRun 1──* AIInvocation
```

Nothing here is over-normalized beyond what provenance and aggregation genuinely require —
`IssueEvidence` is the one table added specifically to satisfy the new provenance requirement, and
it's justified because without it "why was this flagged" has no queryable answer.

---

## 4. AI vs Deterministic Responsibility Matrix

| Responsibility | Owner | Rationale |
|---|---|---|
| Overall sentiment classification | **AI** | Requires language understanding |
| Topic classification | **AI** | Semantic judgment against controlled taxonomy |
| Aspect extraction + aspect-level sentiment | **AI** | Core interpretive task, can't be rule-based reliably |
| Severity classification (per aspect) | **AI**, constrained to enum | Judgment call, but output is a validated enum, not free text |
| Language detection | **AI** (part of same structured call) or a cheap deterministic library (`langdetect`/`fasttext`) | Deterministic library is cheaper and sufficient — **recommend deterministic**, not AI, since it's a solved classification problem that doesn't need an LLM. Flagged as a change from my original plan. |
| Evidence snippet selection | **AI** (must quote from source text; validated as a substring of the original review) | Interpretive, but validated deterministically post-hoc |
| Insight narrative synthesis | **AI**, strictly grounded — prompt is given the computed evidence object only, never raw permission to invent numbers | Requires natural-language synthesis; numbers themselves come from deterministic aggregation, not the LLM |
| Action recommendation text | **AI**, grounded in Issue + IssueEvidence | Requires business judgment/phrasing |
| Public review response drafting | **AI** | Requires natural, contextual writing |
| Validation of all AI outputs | **Deterministic** (Pydantic) | Non-negotiable trust boundary |
| Persistence | **Deterministic** | — |
| Deduplication / idempotency | **Deterministic** (DB constraints + hash) | Must be exact, not probabilistic |
| Aggregation (counts, %s, rollups) | **Deterministic** (SQL) | Must be auditable/reproducible |
| Trend calculation (baseline, % change, threshold/z-score) | **Deterministic** | Explicit requirement: explainable, not ML |
| Priority scoring formula | **Deterministic**, documented weighted formula over configurable weights (frequency, negative sentiment, severity, trend/emerging behavior, affected location(s), rating impact, persistence over time) — exact weights finalized and tested in Phase 5, not fixed in Phase 0 (see §15 Q3) | Must be explainable to a manager; no ML prioritization model |
| Recurring-issue grouping (taxonomy-based, v1) | **Deterministic** (group-by topic/aspect/location/week over a count threshold) | No AI needed once aspects are classified |
| Emerging/novel issue discovery via clustering (deferred) | **AI-assisted (embeddings) + deterministic clustering**, only if/when justified | Genuinely needs semantic similarity; deferred per locked decision #8 |
| Workflow state transitions | **Deterministic** | Must be reliable and auditable |
| Human approval decisions | **Human** (not AI, not deterministic) | The entire point of the human-in-the-loop requirement |
| Scheduling | **Deterministic** (cron) | — |
| Retries/backoff | **Deterministic** (`tenacity`) | — |
| Authorization/authentication | **Deterministic** | Security-critical, must not be probabilistic |
| Notifications | **Deterministic**, triggered by state transitions | — |
| Audit logging | **Deterministic** | Must be complete and tamper-evident |
| Outcome interpretation (improved/worsened) | **Deterministic** (threshold on delta_pct), optionally an AI one-line gloss on top of the deterministic verdict | Verdict must be deterministic; a human-readable gloss can be AI but is decoration, not the source of truth |

**Change from original plan, flagged explicitly:** language detection moves from "AI, investigate
multilingual approach" to **deterministic library-based detection**, with translation-before-analysis
only applied to the subset of non-English reviews that need it before the structured extraction
call. This avoids spending an LLM call on a problem a $0-cost library already solves reliably, and
keeps the AI call budget focused on genuinely interpretive work.

---

## 5. Evidence Provenance Design

Every user-facing claim must resolve to a concrete chain. Technically, this is implemented as:

1. **AggregatePeriodMetric is always the immediate parent of a trend/frequency claim.** A trend
   statement like "waiting-time complaints increased 142%" is never free text — it's rendered from
   two specific `AggregatePeriodMetric` rows (baseline period, current period) plus the formula
   applied to them. The API response for any Insight includes `evidence: { baseline_metric_id,
   current_metric_id, formula, computed_value }`.
2. **IssueEvidence is the join table that lets the dashboard walk from Issue → Insight →
   AggregatePeriodMetric rows → individual ReviewAspect/Review rows.** When a manager clicks
   "why was this flagged," the API resolves: Issue → its IssueEvidence rows → for
   `evidence_type=metric`, show the aggregate numbers and date range/locations; for
   `evidence_type=review_citation`, show the actual review text (a bounded sample, e.g. up to 10
   representative reviews, not all 47 — chosen deterministically, e.g. most recent + most severe).
3. **Every AI-derived field carries its `ai_invocation_id`.** `ReviewAnalysis`, `Insight`, and
   `Action` all FK to the `AIInvocation` row that produced them, so "was this AI-derived or
   deterministic" is answered by a boolean check (`ai_invocation_id IS NOT NULL`), and the exact
   prompt version/model/timestamp is always retrievable for debugging or an interview walkthrough.
4. **Layered groundedness — deterministic facts vs. LLM prose (resolved, see §15 Q4).** The system
   never treats LLM-generated text as the source of truth for a number. The layering is:

   - **Deterministic application layer (source of truth for all facts).** Counts, percentages,
     baseline/current values, date ranges, locations, severity, priority factors, trend values,
     review IDs, and evidence references are all computed and stored by deterministic code
     (`aggregation/`, `issues/` modules) before any LLM is invoked. Nothing numeric ever
     originates from a model.
   - **Evidence object (the only thing the LLM sees).** Immediately before generating an insight,
     the application assembles a structured evidence object from `IssueEvidence` +
     `AggregatePeriodMetric`, e.g.:
     ```json
     {
       "issue": "waiting_time", "location": "Location B",
       "current_period": {"start": "2026-08-04", "end": "2026-08-10", "count": 18},
       "previous_period": {"start": "2026-07-28", "end": "2026-08-03", "count": 9},
       "change_pct": 100.0,
       "representative_review_ids": ["review_123", "review_456", "review_789"]
     }
     ```
   - **LLM responsibility.** The model receives only this object and is instructed to synthesize,
     explain likely business meaning, and produce grounded narrative prose — it is never asked to
     compute or restate a number it wasn't given, and it has no access to raw review counts beyond
     what's in the object.
   - **Dashboard responsibility.** Every numeric fact shown on the dashboard (e.g., "+100%") is
     rendered directly from the deterministic backend field (`delta_pct`), never parsed out of the
     LLM's sentence. The LLM's sentence is displayed alongside the number as explanatory prose, not
     as the number's source — e.g. the UI shows `delta_pct = 100` (from the evidence object) next
     to the generated line *"Waiting-time complaints have increased substantially at Location B,
     suggesting a deterioration in service speed that may require operational attention."*
   - **Regex/number cross-check remains, but only as a secondary safety net**, not the primary
     guarantee: it flags (logs a warning) when the generated prose mentions a number inconsistent
     with the evidence object, handled like any other soft validation failure per §8 — it does not
     block insight display, because the dashboard was never relying on the prose for the number in
     the first place.
5. **API surface for provenance**: `GET /issues/{id}/evidence` returns the full chain (metrics +
   cited reviews + AI invocation metadata) as one payload the dashboard renders as an expandable
   "evidence" panel under every issue/insight card, with numeric fields rendered from their
   deterministic source and the LLM narrative rendered as clearly-labeled explanatory text — this
   satisfies "a user should be able to understand ... which individual reviews support the finding"
   directly and concretely, without ever trusting generated prose as a factual record.

---

## 6. Evaluation Strategy (incremental, not deferred to one final phase)

| Phase | What's evaluated | Test type | How |
|---|---|---|---|
| 3 (AI analysis) | Sentiment/topic/aspect/severity accuracy vs. hand-labeled examples; structured-output validity rate | **AI quality eval** + **unit test** (Pydantic validation itself) | ~40-example labeled subset of the synthetic dataset (see §7), scored for exact/partial match; validity rate = % of raw LLM calls that parse into the Pydantic schema without repair |
| 4 (issue detection) | Does aggregation + grouping correctly rediscover the seeded recurring patterns? | **Data/metric validation** (deterministic, exact-match) | Synthetic dataset is generated with known ground-truth: "wait_time at Location B should show 5/7/9/18 mentions across weeks 1-4." Test asserts the computed `AggregatePeriodMetric` rows match these exactly. |
| 5 (trend/prioritization/insight) | Does the trend engine flag the seeded emerging issue and not flag stable ones? Does the priority formula rank seeded high-severity issues above low ones? Is the LLM insight text grounded (numbers match evidence)? | **Unit test** (formula correctness) + **data validation** (seeded expected priority order) + **AI quality eval** (groundedness check from §5) | Seeded dataset includes both a rising and a flat/declining aspect trend as a negative control |
| 6 (action workflow) | State machine transitions only occur via valid paths; unauthorized/duplicate approvals rejected; audit log complete | **Integration test** (API-level) | Scripted sequences hitting `/issues/{id}/approve` etc., asserting `WorkflowEvent` rows and final states |
| 9 (dashboard) | Every displayed metric matches its source query | **End-to-end test** (API response vs. direct DB query) | For each dashboard panel, a test computes the expected value directly from seed data and compares to the API/dashboard payload |
| 11 (consolidation) | Full regression: all of the above run together, plus a comprehensive AI eval report | **Aggregated CI suite** | pytest suite (unit+integration+data-validation) is CI-blocking; the AI quality eval report (accuracy/validity numbers) is CI-visible but non-blocking, since LLM outputs have expected minor variance run-to-run |

This is deliberately built as **one growing pytest suite with clearly separated markers**
(`@pytest.mark.unit`, `.integration`, `.eval`, `.e2e`) from Phase 3 onward — not a separate testing
phase bolted on at the end. Each phase's Definition of Done includes "tests for this phase's
evaluation row pass," so evaluation is a gate, not an afterthought.

---

## 7. Synthetic Dataset Strategy

The dataset is a **test fixture with known ground truth**, generated by a script (not hand-written
CSV), so it's regenerable and documented. Structure:

- **3 locations**, one business, spanning ~6 months of weekly-bucketed review activity.
- **Deliberately seeded patterns**, each with a documented expected outcome the eval suite checks against:
  - **Recurring negative pattern**: wait-time complaints at Location B rising 5→7→9→18 over 4 weeks
    (emerging issue, should trigger a trend alert).
  - **Recurring positive pattern**: consistent "food quality" praise across all locations (should
    surface as a stable positive aspect, never flagged as an issue).
  - **Declining issue**: a cleanliness complaint pattern at Location A that spikes then falls after
    a simulated "action taken" date — feeds the Outcome/before-after evaluation in Phase 7.
  - **Stable/flat aspect** (negative control): price complaints at a constant low rate — must NOT be
    flagged as emerging.
  - **Multi-aspect reviews**: reviews explicitly combining "great food, slow service" style mixed
    sentiment, to test per-aspect sentiment splitting.
  - **Ambiguous/difficult cases**: sarcasm, backhanded compliments, very short reviews ("meh"),
    reviews with no actionable content ("nice place") — used to sanity-check the model doesn't
    force a confident classification on genuinely thin signal (severity should default low/none).
  - **Multilingual subset**: a small set (~5-8%) of Spanish/French reviews, testing the
    detect-then-translate-then-analyze path.
  - **Duplicates**: exact re-submissions and near-duplicates (same source_review_id resubmitted;
    same content different id) — tests idempotency constraints from §Domain Model.
  - **Malformed/invalid records**: missing required fields, out-of-range ratings, empty text,
    invalid encoding — tests ingestion validation and per-record failure isolation.
  - **Seasonal/temporal variation**: a generic volume increase around a simulated holiday week,
    to make sure trend detection isn't confused by overall volume changes vs. issue-specific ones
    (this is why % change is computed per-aspect, not on raw complaint counts alone).
- **Volume**: ~800-1,200 reviews total — enough for weekly aggregation to be statistically
  meaningful without needing performance-tuning work.
- **Hand-labeled subset** (~40 reviews) carved out specifically for the Phase 3 AI eval, covering
  every category above at least once, with human-assigned expected sentiment/topic/aspect/severity
  recorded in a fixture file (`eval_labels.json`) alongside the generator.

This directly operationalizes "can the system actually discover known patterns" — every seeded
pattern above has a corresponding assertion somewhere in the evaluation suite from §6.

---

## 8. Reliability & Failure Model

| Failure | Detection | Behavior | Recovery |
|---|---|---|---|
| LLM API unavailable | Connection/5xx error | Retry with exponential backoff (`tenacity`, e.g. 3 attempts, capped delay); on final failure, review marked `analysis_status=pending_retry` (its `ingestion_status` is untouched and stays `accepted`), `AIInvocation` logged with `error_type=provider_error` | Next scheduled analysis run picks up all `analysis_status=pending_retry` reviews automatically — no data loss, just delayed enrichment |
| LLM timeout | Explicit per-call timeout (e.g. 30s) | Treated as a transient failure, same retry path as above | Same as above |
| LLM returns invalid structured output | Pydantic validation failure | One repair attempt (re-prompt with the validation error appended); if still invalid, review marked `analysis_status=failed`, `AIInvocation.validation_passed=false`, error captured | Visible in System Health view; manual or scheduled reprocessing sweep can retry `analysis_status=failed` items after investigation |
| Individual review analysis fails (any reason) | Exception in per-review loop | Caught per-item; run continues to next review; `analysis_status` updated on that review + run counters incremented | Doesn't block the batch; `ProcessingRun.reviews_failed` surfaces it |
| Database operation fails | Exception/connection error | Transaction rolled back for that unit of work; for a batch job, per-item try/except keeps the rest of the batch alive; a full DB outage fails the whole `ProcessingRun` with status=failed | Job is safely re-runnable (idempotent) once DB is back — no partial-write corruption because each review's write is one transaction |
| Duplicate feedback arrives | Unique constraint violation on ingestion | Rejected at insert with `ingestion_status=duplicate`, not an error — `analysis_status` is never set for it — logged as an expected outcome, not a failure | No action needed; visible in ingestion stats |
| Scheduled processing partially fails | Run completes with `reviews_failed > 0` | `ProcessingRun.status = 'completed_with_errors'` (not silently "success") | Failed items are queryable and reprocessable individually |
| Entire processing run fails | Unhandled top-level exception | `ProcessingRun.status='failed'`, Sentry alerts, no partial commit assumed beyond already-committed per-item transactions | Next scheduled run naturally retries anything left `pending`/`pending_retry` |
| Insight cannot be generated | LLM failure or evidence insufficient (e.g., too few data points) | Issue stays in `identified`/`reviewed` state without an Insight attached rather than showing a fabricated one; dashboard shows "insight pending" | Regenerated on next trend-detection run once more evidence/successful AI call is available |
| Approved action fails (e.g., simulated publish step errors) | Exception in action-execution step | Action reverts to `approved` (not silently marked resolved), error logged to `WorkflowEvent` | Retryable by re-triggering execution; never auto-escalates state past what actually succeeded |

**Explicitly not built**: dead-letter queues as separate infrastructure (a `status='failed'` column
plus a reprocessing sweep job serves the same purpose at this scale), circuit breakers (traffic
volume doesn't justify one), multi-region failover (out of scope for a portfolio deployment).

---

## 9. Observability Design

**Technical observability** — answers "is the system working," queried from `ProcessingRun` +
`AIInvocation` + Sentry + platform logs, surfaced in a dedicated `/system-health` dashboard route:
run history with success/failure counts and duration, per-AI-operation latency/token/cost
breakdown, failed-review list with error reasons and a "reprocess" action, Sentry-linked error
detail.

**Business/VoC analytics** — answers "what's happening with customers," computed from
Review/ReviewAspect/AggregatePeriodMetric/Issue/Insight/Action/Outcome, surfaced in the main
dashboard: feedback volume/rating/sentiment/language distributions, topic/aspect breakdowns,
recurring/emerging issues with severity/trend/locations, action pipeline (proposed → pending →
approved → resolved), outcome before/after comparisons.

These two views share no components and no queries — deliberately, per the mentor requirement and
your own original spec, so the business dashboard never leaks technical/operational detail to a
non-technical viewer, and the system-health view never gets diluted with business KPIs.

Tooling: **Sentry** (errors/exceptions) + **structured JSON logs** to stdout (captured by Render's
log viewer) + **own DB tables** (the only source for metrics/traces/LLM-observability). No
Prometheus/Grafana/OpenTelemetry/Langfuse — each solves a scale or multi-service-tracing problem
this single-service project doesn't have; revisit only if a concrete need emerges (see §15).

---

## 10. Security Design

- **Secrets**: `.env` (gitignored from the first commit) + committed `.env.example` with placeholder
  values; real values only in Render/Vercel environment variable settings. No secret is ever
  hardcoded or logged.
- **Authentication**: single admin account, bcrypt-hashed password, JWT session token, gating every
  write/approval endpoint (`POST/PUT` on reviews-batch-ingest-trigger, issues, actions, approvals).
  Read-only analytics endpoints stay public for demo accessibility. This is intentionally minimal —
  **no RBAC**, no multi-user roles, per locked decision #19.
- **Input validation**: Pydantic schemas on every request body; rejects malformed/oversized payloads
  before they reach business logic.
- **CORS**: restricted to the deployed Vercel frontend origin (and localhost during dev) only.
- **Rate limiting**: lightweight in-memory limiting (`slowapi`) on ingestion and auth endpoints to
  blunt naive abuse — no Redis-backed distributed limiter needed at this scale.
- **Logging restrictions**: raw review text and LLM prompts are never written to Sentry breadcrumbs
  or INFO-level logs — only IDs, counts, and status codes. Full text stays in Postgres only.
- **PII minimization**: no real customer identities anywhere in the system (synthetic
  pseudonymous reviewer names only); schema has no email/phone/payment fields.
- **Database security**: managed Postgres (Render) with TLS connections, credentials only via env
  vars, no public DB port exposure beyond the managed provider's default (private networking where
  the platform supports it).
- **Public GitHub safety**: final pre-push checklist — grep for key-shaped strings, confirm `.env`
  is gitignored and never was committed, confirm `.env.example` has no real values, `SECURITY.md`
  documents the threat model and what a real production deployment would additionally need
  (proper secrets manager, encryption-at-rest specifics, PII handling policy, rate limiting at the
  edge/CDN layer).

This is intentionally proportionate — no Vault, no enterprise IAM, no WAF — matching the mentor's
explicit "do not create enterprise-grade infrastructure for no reason" instruction.

---

## 11. API / Module Boundary Proposal

Backend organized as internally-cohesive modules with narrow interfaces (not microservices — one
deployable FastAPI app):

- `ingestion/` — review intake, validation, dedup. Owns `Review`.
- `analysis/` — AI client wrapper, Pydantic schemas for AI I/O, retry/timeout logic. Owns
  `ReviewAnalysis`, `ReviewAspect`, `AIInvocation`. Only module allowed to call the Claude API.
- `aggregation/` — deterministic rollups. Owns `AggregatePeriodMetric`. Pure SQL/pandas-free
  computation, no AI calls, fully unit-testable.
- `issues/` — recurring-issue grouping, trend detection, prioritization. Owns `Issue`,
  `IssueEvidence`. Depends on `aggregation` output only.
- `insights/` — grounded LLM synthesis. Owns `Insight`. Depends on `issues` evidence; second (and
  last) module allowed to call the AI client (via `analysis`'s wrapper, not a new one).
- `actions/` — recommendation, approval workflow, outcome tracking. Owns `Action`,
  `ActionApproval`, `Outcome`.
- `workflow/` — shared state-machine + audit logging utility used by `issues` and `actions`. Owns
  `WorkflowEvent`.
- `auth/` — login, JWT issuance/verification, dependency-injected auth guard for protected routes.
- `observability/` — `ProcessingRun` lifecycle helper, structured logging setup, Sentry init. Used
  by every job/module but owns no business entities.
- `scheduling/` — cron job entrypoints that orchestrate the above modules in sequence.

Indicative endpoint surface (finalized during Phase 2/6/9, not committed to exactly yet):

```
POST   /reviews                  POST   /reviews/batch          GET /reviews
GET    /analytics/overview       GET /analytics/issues          GET /analytics/aspects
GET    /issues                   GET /issues/{id}                GET /issues/{id}/evidence
POST   /issues/{id}/approve      POST /issues/{id}/dismiss
GET    /actions                  POST /actions/{id}/approve      POST /actions/{id}/reject
POST   /actions/{id}/complete    GET /actions/{id}/outcome
GET    /system-health/runs       GET /system-health/runs/{id}   GET /system-health/failed-reviews
POST   /system-health/failed-reviews/{id}/reprocess
POST   /auth/login
```

---

## 12. Final Technology Stack

| Layer | Choice | Status |
|---|---|---|
| Backend | Python + FastAPI | Locked |
| Database | PostgreSQL | Locked |
| ORM | SQLAlchemy 2.0 | Locked |
| Migrations | Alembic | Locked |
| LLM | Anthropic Claude, structured/tool-use output | Locked |
| Output validation | Pydantic | Locked |
| Language detection | Deterministic library (`langdetect` or `lingua`), not an AI call | New (see §4) |
| Retry/backoff | `tenacity` | New, implements locked reliability requirement |
| Issue detection v1 | Taxonomy-based + deterministic aggregation | Locked |
| Embeddings/clustering | Deferred | Locked |
| Trend detection | Deterministic statistics (baseline, % change, threshold) | Locked |
| Frontend | Next.js + React | Locked |
| Charts | Recharts or Tremor | Locked |
| Scheduling | Platform cron (Render cron jobs); APScheduler only as local-dev fallback | Locked |
| Task queue | None (no Celery/Redis) | Locked |
| Error tracking | Sentry | Locked |
| App logs | Structured JSON, stdout → platform log viewer | Locked |
| LLM observability | `ProcessingRun` + `AIInvocation` tables | Locked |
| Business analytics | Dedicated dashboard views | Locked |
| Technical observability | Separate `/system-health` view | Locked |
| Auth | Single-admin JWT, no RBAC | Locked |
| Notifications | In-app feed | Locked |
| Rate limiting | `slowapi` (in-memory) | New, minimal addition |
| Data | Generated synthetic dataset with seeded ground truth | Locked, strengthened per §7 |
| Deployment | Render (API+DB+cron) + Vercel (frontend) | Locked |
| CI/CD | GitHub Actions | Locked |
| Secrets | `.env`/`.env.example` + platform env vars | Locked |
| Review responses | Human-approved, simulated publish | Locked |
| Agents | None — deterministic orchestration | Locked |
| Testing | pytest (unit/integration/eval/e2e markers) | Standard |

---

## 13. Final Phased Implementation Plan

**Phase 0 — Discovery & Architecture** *(this document)*
DoD: user approves this package.

**Phase 1 — Foundation & Reliability Scaffolding**
Builds: repo layout per module boundaries (§11), FastAPI skeleton, Postgres + Alembic, `.env.example`,
Sentry + structured JSON logging, `tenacity` retry helper, base `ProcessingRun`/`AIInvocation`/
`WorkflowEvent` tables + migrations, Dockerfile, GitHub Actions CI (lint + pytest scaffold, currently
empty suite), auth module skeleton (login endpoint, JWT).
Technical concepts: layered app structure, migration discipline, observability-as-foundation.
Business concepts: none yet — pure scaffolding.
Evaluation introduced: CI pipeline itself (asserts the app boots and a health endpoint responds).
Dependencies: none.
DoD: `docker compose up` runs API+DB; CI green on an empty-but-structured repo; login issues a JWT.
Not yet built: any domain tables beyond the observability/audit ones, any AI integration.

**Phase 2 — Domain Model & Review Ingestion + Synthetic Dataset**
Builds: full source-of-truth schema (Business, Location, Review, taxonomy tables), synthetic
dataset generator implementing §7 (seeded patterns + `eval_labels.json`), `POST /reviews`,
`POST /reviews/batch`, `GET /reviews`, idempotency constraints, per-item validation.
Technical concepts: idempotent ingestion, constraint-based dedup, deterministic language detection.
Business concepts: what "structured feedback" looks like before any interpretation.
Evaluation introduced: ingestion-level data validation tests (duplicates rejected, malformed
records isolated, unique constraints hold) — deterministic, CI-blocking from this phase on.
Dependencies: Phase 1.
DoD: full synthetic dataset ingests idempotently; a second identical batch run produces zero new
rows; malformed/duplicate records are correctly classified, not silently dropped or crashing.
Not yet built: any AI analysis, any aggregation.

**Phase 3 — AI Analysis Pipeline**
Builds: Pydantic I/O schemas, Claude structured-output client wrapper (in `analysis/`), per-review
analysis job with retry/timeout/dead-letter per §8, `ReviewAnalysis` + `ReviewAspect` tables,
`AIInvocation` logging on every call.
Technical concepts: structured-output contracts, validation-as-trust-boundary, provenance linkage
(`ai_invocation_id`) established from the first AI-touching table onward.
Business concepts: sentiment vs. topic vs. aspect vs. severity as distinct, separately-stored
signals.
Evaluation introduced: **AI quality eval** against the Phase 2 hand-labeled subset (accuracy +
structured-output validity rate), reported in CI (non-blocking) alongside the now-growing
deterministic suite (blocking).
Dependencies: Phase 2 (needs ingested reviews + labeled eval set).
DoD: full dataset processed; failure-injection test confirms a forced malformed response
dead-letters correctly without corrupting `ReviewAnalysis`; eval report shows a defensible baseline
accuracy (target documented, not necessarily "high" — the point is having the number).
Not yet built: aggregation, issue detection, insights, actions.

**Phase 4 — Aggregation & Recurring-Issue Detection**
Builds: `AggregatePeriodMetric` computation job (weekly rollups by topic/aspect/location),
taxonomy-based grouping into `Issue` rows, `IssueEvidence` linkage from issues back to the
contributing metrics and representative reviews.
Technical concepts: derived-vs-source-of-truth data separation, provenance table design in
practice.
Business concepts: "recurring" as a concrete, countable, re-derivable thing rather than a vibe.
Evaluation introduced: **data/metric validation** against the seeded ground truth in §7 (exact
count assertions per week/location/aspect) — CI-blocking.
Dependencies: Phase 3.
DoD: seeded wait-time pattern is correctly aggregated and promoted to an `Issue`; `IssueEvidence`
correctly links it to the specific contributing reviews; a stable/flat aspect is NOT promoted.
Not yet built: trend math, prioritization, LLM insight text, actions.

**Phase 5 — Trend Detection, Prioritization & Grounded Insights**
Builds: baseline/% change/threshold trend engine; priority formula with its **weights finalized
and documented in this phase** (not fixed in Phase 0 — see §15 Q3), over factors frequency,
negative sentiment, severity, trend/emerging behavior, affected location(s), rating impact, and
persistence over time; weights are configuration values, not hard-coded magic numbers, and are
tested against the seeded dataset's expected issue ordering; `priority_score_breakdown` stored per
issue; grounded `Insight` generation (LLM synthesis constrained to the evidence object, per §5's
layered groundedness contract).
Technical concepts: explainable statistics, prompt-grounding technique, provenance completed
end-to-end (Insight → IssueEvidence → AggregatePeriodMetric → Review).
Business concepts: emerging vs. stable vs. declining issues; what "priority" means and why.
Evaluation introduced: unit tests on the trend/priority formulas + data validation on seeded
rising/flat/declining trends + **AI quality eval** extended to check insight groundedness
(numbers-in-text vs. evidence-object cross-check from §5).
Dependencies: Phase 4.
DoD: seeded emerging issue triggers a correctly-worded, correctly-grounded alert; seeded flat
trend does not; priority ranking of multiple seeded issues matches the documented formula's
expected order.
Not yet built: actions/approval workflow.

**Phase 6 — Recommended Actions & Human Approval Workflow**
Builds: `Action`/`ActionApproval` tables, full workflow state machine + `WorkflowEvent` audit
logging (shared `workflow/` module), grounded action-recommendation LLM call, approval endpoints.
Technical concepts: state machines as first-class, deterministic-execution-after-human-approval
pattern.
Business concepts: the distinction between an AI recommendation and an approved operational
action — the core human-in-the-loop concept of the whole project.
Evaluation introduced: **integration tests** on state transitions (valid/invalid paths, audit
completeness) — CI-blocking.
Dependencies: Phase 5.
DoD: an issue can be walked identified→...→resolved via API calls with a complete, correct audit
trail; invalid transitions (e.g., approving an already-rejected action) are rejected.
Not yet built: outcome tracking, dashboard, review-response workflow, scheduling.

**Phase 7 — Outcome Monitoring**
Builds: `Outcome` computation comparing pre/post-action `AggregatePeriodMetric` for an issue's
topic/aspect, deterministic improved/worsened/no-change verdict.
Technical concepts: closing the loop — action effectiveness as a re-derivable metric, not a claim.
Business concepts: did the business response actually work.
Evaluation introduced: data validation against the seeded declining-issue-after-action pattern
from §7.
Dependencies: Phase 6.
DoD: the seeded post-action-improvement scenario produces a correct `Outcome` row and verdict.
Not yet built: dashboard UI, scheduling, review-response workflow.

**Phase 8 — Review Response Workflow — DROPPED (2026-09-08 roadmap decision)**
Status: **will not be built.** Originally optional/stretch scope (§15 Q1); the user has
now formally dropped it entirely rather than leaving it open as a possible stretch item.
It is considered a future client-specific extension outside this portfolio project's
scope, not a gap in it. The core VoC narrative (feedback → understanding → recurring
issue → trend → prioritization → evidence → recommended action → approval → action →
outcome) is fully delivered without it. The `public_review_response` `Action.type`
value remains in the domain model (harmless, already shipped in Phase 6) so the
architecture stays capable of this later without it being a dependency of anything else
— but no further work on it is planned.
Revised remaining roadmap: Phase 9 — Dashboard; Phase 10 — Scheduled Jobs +
Notifications; Phase 11 — Reliability, Observability, Security + Evaluation Hardening;
Phase 12 — Deployment + Production Documentation.
Not yet built: dashboard, scheduling (irrelevant if this phase is skipped).

**Phase 9 — Dashboard — COMPLETE**
Builds: Next.js app — business views (Feedback Overview, Customer Experience, Issues, Actions,
Outcomes) consuming existing read endpoints + a `/issues/{id}/evidence` provenance panel; separate
System Health view for `/system-health/*`.
Technical concepts: read-model API design, provenance UI pattern (expandable evidence).
Business concepts: none new — this phase makes existing business concepts visible/actionable.
Evaluation introduced: **end-to-end tests** — dashboard payload vs. direct DB query, per §6.
Dependencies: Phases 4-7 (data to display), Phase 6 (approval actions to wire up).
DoD: every dashboard panel's numbers are asserted against source-of-truth queries in a test;
approve/reject buttons function against real endpoints.
Not yet built: scheduled automation (jobs still triggered manually/via script through this phase).

**Phase 10 — Scheduling & Notifications — COMPLETE**
Builds: `scripts/run_pipeline.py` chaining aggregation→issue detection→trend/priority
recompute→outcome evaluation (all deterministic/free; analysis and insight generation
are opt-in-only flags, off by default, to protect API budget); `render.yaml` Render Cron
Job spec wrapping it (provisioning itself is Phase 12); in-app `Notification` model +
service + `GET /notifications` / `POST /notifications/{id}/read` triggered off two
specific events — a brand-new high-severity `Issue` (not a re-detected one) and an
`Action` reaching `awaiting_approval`; a header notification bell in the dashboard
(`frontend/components/NotificationBell.tsx`, polling every 30s).
Technical concepts: cron-triggered `ProcessingRun` orchestration (via
`ProcessingRunTrigger.CRON`, same code path as manual), notification-as-side-effect-of-
state-transition (deterministic, not AI-triggered).
Business concepts: the system operating continuously rather than only on-demand.
Evaluation introduced: `tests/test_pipeline.py` asserts a cron-triggered run produces
identical results (status, scope, success count) to an equivalent manually-triggered
one; `tests/test_notifications.py` covers both notification triggers, idempotency
(re-running detection doesn't duplicate a notification), and read/unread state.
Dependencies: Phases 1-9 complete.
DoD: `scripts/run_pipeline.py` verified live against the real seeded dataset and Docker
deployment (free — no AI flags passed); the notification bell verified live in the
browser end-to-end (unread badge, dropdown, click-through-to-issue with mark-as-read)
after rebuilding the API image, which had gone stale mid-session. Actual scheduled
execution in a deployed environment is Phase 12's job — this phase delivers the
orchestration script and the notification feature working correctly on demand.
Not yet built: nothing pipeline-wise — this is the last functional phase.

**Phase 11 — Evaluation Consolidation & Hardening Pass — COMPLETE**
Builds: `evaluation/` package consolidating all per-phase evaluation code —
`evaluation/ai_quality.py` (the Phase 3 AI-quality eval, moved from `scripts/` with
`scripts/evaluate_ai_analysis.py` kept as a thin CLI wrapper for backward
compatibility), `evaluation/report.py` (pure, deterministic report-building logic),
`evaluation/generate_report.py` (assembles `evaluation/EVAL_REPORT.md` from the live
pytest suite + the committed AI-quality artifact). Reviewed the codebase for
TODO/FIXME/edge-case gaps (found none — every documented limitation from earlier phases
was already an intentional, written decision, not an oversight) and reviewed the
hand-labeled eval set for coverage gaps (found none justifying further real-API spend
given the existing 100%-across-the-board result).
Technical concepts: evaluation-as-artifact (a report you can show, not just "tests
pass"); the AI-quality eval stays a deliberately manual, non-CI step per ADR-9 and this
project's real API budget constraint — `evaluation/generate_report.py` never re-runs it,
only reads the artifact from the one real run already performed in Phase 3.
Business concepts: none new — this phase is about confidence and defensibility.
Evaluation introduced: `evaluation/generate_report.py` runs the full deterministic
pytest suite (75 tests, all passing) split by marker and reads the committed AI-quality
report (48 hand-labeled examples, 100% sentiment/aspect/validity accuracy from the
Phase 3 real-API run); `tests/test_evaluation_report.py` unit-tests the report-building
logic itself with synthetic inputs.
Dependencies: all prior phases.
DoD: `pytest` full run green (75/75); `evaluation/EVAL_REPORT.md` committed and
regenerable via `python evaluation/generate_report.py` with accuracy numbers explained
and sourced back to the exact real-API run that produced them.
Not yet built: nothing new — pure consolidation. No new real API spend this phase.

**Phase 12 — Deployment & Documentation**
Builds: Render deployment (API+DB+cron), Vercel deployment (frontend), final secrets audit,
README/ARCHITECTURE.md/DECISIONS.md/SECURITY.md/API docs, demo screenshots/walkthrough,
limitations & future-work section.
Technical concepts: production deployment of a multi-service portfolio app.
Business concepts: none new — this phase packages the story for an audience.
Evaluation introduced: none new — CI must be green as a deployment gate.
Dependencies: all prior phases.
DoD: a stranger can clone the repo, run it locally from `.env.example`, and separately view the
live deployed demo; documentation covers setup, architecture, security, testing, limitations.

---

## 14. Architecture Decision Log (ADR-style)

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| ADR-1 | Taxonomy-based issue detection for v1; embeddings/clustering deferred | Embeddings from day one | Taxonomy is explainable and sufficient for known-category issues; clustering adds real complexity (labeling, stability) not justified until a concrete "novel issue we're missing" case appears in the data |
| ADR-2 | Deterministic library for language detection, not an LLM call | AI-based language detection as part of the structured call | Solved problem, near-zero cost via a library; saves LLM budget for genuinely interpretive tasks |
| ADR-3 | No task queue (Celery/Redis) | Celery+Redis for async fan-out | Batch/periodic workload profile doesn't need distributed workers; cron + in-process job is simpler and equally reliable at this volume |
| ADR-4 | Own `ProcessingRun`/`AIInvocation` tables instead of Langfuse | Langfuse | Small number of well-defined single-purpose AI calls; a homegrown table gives the same answers, queryable from the same dashboard stack, zero added infra |
| ADR-5 | Single-admin JWT auth, no RBAC | Multi-role RBAC (manager/location-lead/exec) | Project's approval workflow needs *an* authenticated actor, not a permission hierarchy; RBAC would be unjustified complexity for a single-tenant demo |
| ADR-6 | In-app notifications, not email | Email via Resend/Postmark | Avoids deliverability/domain setup for a portfolio project; can be added later without architecture change (notification is already a distinct deterministic step) |
| ADR-7 | Render (API+DB+cron) + Vercel (frontend) | Single-platform (Railway or Render-only) | Best native fit for FastAPI+Postgres+cron (Render) and for Next.js (Vercel) respectively; avoids compromising either side for the sake of one platform |
| ADR-8 | Insight/action LLM calls strictly grounded in a pre-computed evidence object | Free-form LLM synthesis from raw data | Directly implements the evidence-provenance requirement; prevents unsupported numeric claims |
| ADR-9 | Evaluation built incrementally per phase, not as a final Phase 11 activity | Traditional "testing phase at the end" | Each phase's own ground-truth (seeded data, labeled examples) is freshest and most relevant to write tests against right when that phase is built |
| ADR-10 | `Review` lifecycle split into `ingestion_status` and `analysis_status` | Single combined `status` field | A review can be successfully ingested and independently fail/retry in analysis; one field couldn't represent both states without ambiguity |
| ADR-11 | Groundedness enforced via deterministic-fields-as-source-of-truth + evidence-object-constrained LLM prose, with regex cross-check as a secondary safety net only | Regex number-matching as the primary factual guarantee | Free-text number matching is brittle and was never a real guarantee; the dashboard never needs to trust a number out of generated prose because it renders numeric facts from backend fields directly |
| ADR-12 | Phase 8 (public review-response workflow) demoted to optional/stretch, then formally dropped entirely (2026-09-08) | Keep it as a required core phase; or keep it open-ended as a stretch item | It duplicates the human-in-the-loop pattern already proven in Phase 6; the core VoC narrative is complete without it; treated as a future client-specific extension outside this portfolio's scope |

---

## 15. Open Questions — RESOLVED

All six open questions from the prior draft are now decided. Nothing below is open for
implementation-time reinterpretation without a deliberate revisit.

| # | Open Question | Final Decision | Reason |
|---|---|---|---|
| 1 | Phase 8 (review-response workflow) priority | **Demoted to optional/stretch scope.** Not a dependency of any other phase; the `public_review_response` `Action.type` stays in the domain model so the architecture remains capable of it, but the project is complete without building it. | Duplicates the human-in-the-loop pattern already proven in Phase 6; the core VoC narrative (feedback → issue → trend → priority → evidence → action → approval → outcome) doesn't need a second workflow instance to be demonstrated |
| 2 | AI-call budget for language detection | **Deterministic library** (`langdetect`/`lingua`), not an LLM call. Schema (`Review.detected_language`) supports multilingual data from the start; no large multilingual infrastructure is built. | Language ID is a solved, near-zero-cost classification problem — spending LLM budget on it would blur the AI-vs-deterministic boundary the project is built to demonstrate |
| 3 | Priority score formula weights | **Not fixed in Phase 0.** The factors are locked (frequency, negative sentiment, severity, trend/emerging behavior, affected location(s), rating impact, persistence over time); the *weights* are configuration values finalized, documented, and tested against the seeded dataset's expected issue ordering during Phase 5. No ML prioritization model. | Weighting is a product judgment best made against real seeded-data behavior, not decided abstractly before the trend engine exists |
| 4 | Groundedness: regex vs. layered guarantee | **Layered design adopted** (§5 point 4): deterministic backend fields are the sole source of truth for every number; the LLM receives only a structured evidence object and produces explanatory prose; the dashboard renders numeric facts directly from backend fields, never from parsed LLM text; the regex/number cross-check is retained only as a secondary, non-blocking safety net. | Regex-matching free text was never a real factual guarantee — the deterministic-fields-plus-grounded-prose split is the actual guarantee, and is more defensible in an interview |
| 5 | Synthetic dataset size | **Approved as proposed**: ~800-1,200 reviews, 3 locations, ~6 months, weekly buckets, all previously specified seeded scenarios retained, ~40-example labeled eval subset retained. | Sufficient for every seeded pattern and all aggregation/trend assertions without requiring performance-tuning scope that isn't otherwise needed |
| 6 | Deployment cost tier | **Lowest practical-cost configuration initially; free-tier sleep behavior is accepted, not engineered around.** Render (API+DB+cron) + Vercel (frontend) as already decided; no architecture change to avoid sleeping. If scheduled jobs later require always-on infrastructure, that's evaluated at deployment time (Phase 12), not designed for now. | Paying for infrastructure solely to keep a portfolio demo from sleeping is scope/cost creep; documented as a deliberate cost decision, not an architectural gap |

No further open questions block implementation. Anything not listed here that surfaces during
build should be handled as a normal implementation-time decision within the locked architecture,
not treated as requiring a new Phase 0 review.

---

## 16. Explicitly Deferred / Out of Scope for v1

These are deliberate exclusions — the simplest architecture that still demonstrates the required
production concepts — not gaps or oversights:

- AI agents (LangGraph, AutoGen, CrewAI, or any agentic planning loop) — deterministic orchestration
  only (§ mentor point 26, ADR context)
- Message queues / Redis / Celery (ADR-3) — database-backed pending work + cron instead
- Kubernetes — single-service deploys on Render/Vercel are sufficient
- Multi-provider LLM abstraction — Anthropic Claude only; no provider-swap interface layer
- Multi-tenant architecture — `Business`/`Location` scoping exists in the schema, but no tenant
  isolation, billing, or per-tenant auth is built
- RBAC / enterprise IAM — single-admin JWT auth only (ADR-5)
- Embeddings/clustering for novel/unknown-issue discovery (ADR-1) — taxonomy-based detection only
  for v1; clustering remains a documented future extension
- Advanced ML-based trend detection — deterministic baseline/%-change/threshold statistics only
- Advanced ML-based prioritization — deterministic, documented, configurable weighted formula only
- Langfuse (ADR-4) — homegrown `ProcessingRun`/`AIInvocation` telemetry
- Prometheus/Grafana/OpenTelemetry — Sentry + structured logs + own DB tables cover the stated
  observability requirements at this scale
- Full public review-platform publishing integration — Phase 8's "publish" step is simulated, not a
  real integration with any review platform's API
- Complex external review-platform integrations (Google/Yelp API ingestion, etc.) — synthetic
  dataset only for v1; the ingestion module's shape (`source` enum, per-source normalization) would
  make a later real integration additive, not a rearchitecture, if ever pursued

---

## 17. Remaining Risks / Limitations

- **LLM output variability**: structured-output validity and classification accuracy are evaluated
  (Phase 3+) but not guaranteed to be perfect; the dead-letter/retry path (§8) is the safety net,
  and the AI eval report makes the actual accuracy visible rather than assumed.
- **Free-tier deployment sleep** (§15 Q6, accepted trade-off): a genuinely "always-on" demo isn't
  guaranteed on the free tier; the README/demo instructions will note how to trigger a run manually
  if a viewer catches it asleep.
- **Single-admin auth**: adequate for a portfolio demo but explicitly not production-grade
  multi-user security; documented as such in `SECURITY.md` rather than overstated.
- **Taxonomy coverage**: recurring/emerging issue detection is only as good as the seeded
  topic/aspect taxonomy (§3) — a genuinely novel complaint category outside that taxonomy won't be
  caught in v1 (this is the explicit, documented reason embeddings/clustering exist as a future
  extension, not a hidden gap).
- **Synthetic-only data**: patterns are realistic but authored, not sourced from real customer
  behavior — sufficient to prove the pipeline works correctly, not to claim real-world model
  performance.

---

No implementation, scaffolding, or application code will begin until this final package is
acted upon. **Phase 0 is complete. No Phase 1 implementation has started.**
