# Review Manager / Voice of Customer

Customer feedback intelligence and feedback-to-action automation for a multi-location
restaurant business. See [PHASE0_ARCHITECTURE.md](PHASE0_ARCHITECTURE.md) for the full
architecture package (domain model, AI/deterministic responsibility matrix, evidence
provenance design, reliability model, phased implementation plan).

**Status:** Phases 1-7 and 9-11 complete (Foundation; Domain Model, Ingestion &
Synthetic Dataset; AI Analysis Pipeline; Aggregation & Recurring-Issue Detection; Trend
Detection, Prioritization & Grounded Insights; Recommended Actions & Human Approval;
Outcome Monitoring; Dashboard; Scheduled Jobs + Notifications; Evaluation Consolidation
& Hardening). **Phase 8 (public review-response workflow) has been formally dropped** —
a future client-specific extension outside this portfolio's scope, not a gap in it.
Remaining: Phase 12 (Deployment + Production Documentation).

## Local setup

Requirements: Python 3.12, Docker.

```bash
cp .env.example .env          # then edit JWT_SECRET / ADMIN_PASSWORD for anything beyond local dev
docker compose up -d --build  # starts Postgres + the API (runs migrations automatically)
curl http://localhost:8000/health
```

API docs (Swagger UI): http://localhost:8000/docs

Log in as the seeded admin (from `.env`'s `ADMIN_EMAIL`/`ADMIN_PASSWORD`):

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"change-me-in-env"}'
```

### Running without Docker

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d db          # still need Postgres
alembic upgrade head
uvicorn app.main:app --reload
```

### Tests

```bash
source .venv/bin/activate
pytest -v
ruff check .
```

Tests always run against a separate `<database>_test` database (created automatically) —
never against the dev database configured in `.env`, so `pytest` is safe to run alongside
a running `docker compose` stack without touching its data.

### Synthetic dataset

```bash
source .venv/bin/activate
python scripts/generate_synthetic_dataset.py           # writes data/synthetic/*.json (deterministic, seeded)
python scripts/load_synthetic_dataset.py --duplicates --malformed   # seeds Business/Locations, ingests via the real API pipeline
```

`generate_synthetic_dataset.py` produces ~1,000 reviews across 3 locations and 26 weeks
with deliberately seeded patterns (an emerging wait-time issue, a cleanliness issue that
improves after a simulated action, a stable positive pattern, a flat negative control,
multilingual/ambiguous/sarcastic examples, duplicates, and malformed records) — see
`data/synthetic/manifest.json` for the exact ground truth and
[PHASE0_ARCHITECTURE.md](PHASE0_ARCHITECTURE.md) §7 for the full design rationale.
`load_synthetic_dataset.py` ingests it through `app.ingestion.service.ingest_batch` (the
same code path the API uses), so re-running it is idempotent — a second run accepts zero
new reviews.

### AI analysis (Phase 3)

Requires `ANTHROPIC_API_KEY` in `.env`. Without it, analysis fails fast at the run level
(no reviews are touched) rather than dead-lettering everything — see
`app/analysis/service.py::analyze_pending_reviews`.

```bash
source .venv/bin/activate
python scripts/run_analysis.py --limit 200        # analyzes pending reviews, prints a ProcessingRun summary
python scripts/evaluate_ai_analysis.py            # AI quality eval against data/synthetic/eval_labels.json
```

Or via the API: `POST /analysis/run?limit=200` (auth required) — same underlying call,
useful for triggering a run without shell access to the container.

The evaluation script re-analyzes the ~40 hand-labeled examples, compares them against
`data/synthetic/eval_labels.json`, and writes `data/synthetic/eval_report.json` with
overall-sentiment accuracy, aspect recall, aspect-sentiment accuracy, and the
structured-output validity rate (§6 of PHASE0_ARCHITECTURE.md) — measuring Claude's
classification quality, not the deterministic pipeline around it (that's what
`tests/test_analysis.py`, fully mocked, already covers in CI).

### Aggregation & recurring-issue detection (Phase 4)

Runs on top of whatever reviews have been AI-analyzed (Phase 3) — safe to run with zero
analyzed reviews (produces zero metrics/issues, not an error).

```bash
source .venv/bin/activate
python scripts/run_aggregation.py --business-name "The Local Table"   # aggregates, then detects issues
```

Or via the API: `POST /aggregation/run?business_id=...` then `POST /issues/detect?business_id=...`
(both auth required), then `GET /issues?business_id=...` and `GET /issues/{id}/evidence`
for the full provenance chain (§5 — every issue traces back to the specific weekly
metrics and representative reviews behind it).

`app/aggregation/service.py` computes weekly (Monday-aligned) `AggregatePeriodMetric`
rows per (location, topic, aspect) plus a business-wide rollup, upserting by natural key
so re-running it never duplicates rows or breaks existing evidence links.
`app/issues/service.py` promotes a (topic, aspect, location) combination to an `Issue`
only when it has at least 2 weeks with 5+ negative mentions — deliberately simpler than
Phase 5's trend engine (this answers "is it recurring," not "is it accelerating"), and
tuned so the synthetic dataset's flat price/value negative control does **not** get
promoted while the seeded wait-time pattern does (see `tests/test_issues.py`).

### Trend detection, prioritization & grounded insights (Phase 5)

All free/deterministic except the final insight-generation step:

```bash
source .venv/bin/activate
python scripts/generate_synthetic_dataset.py   # (if not already done)
```

Or via the API (all auth required):

```
POST /issues/recompute-priority?business_id=...   # free — trend classification + priority scoring, no AI
POST /issues/{issue_id}/insight                    # ONE Claude call (or a free deterministic-template
                                                    # fallback if ANTHROPIC_API_KEY isn't set) — costs money, use sparingly
POST /insights/generate?business_id=...&limit=5    # batch — one call per issue, defaults to a small limit
```

`app/issues/trend.py` compares the most recent 4 weeks of negative mentions against the
preceding 4-week baseline (the same framing as "complaints increased 142% vs. the
previous four-week baseline") — classified as `emerging`/`declining`/`stable`/`new`, no
ML. `app/issues/priority.py` combines frequency, severity, trend, rating impact,
persistence, and location spread into an explainable `priority_score`, with every
factor's raw value/weight/contribution stored in `priority_score_breakdown` — see
`tests/test_trend_and_priority.py` for the seeded emerging/declining/stable cases this
is tested against.

`app/insights/` generates the grounded narrative: the LLM only ever receives a
pre-computed evidence snapshot (counts, baseline, % change, representative review
quotes) and is instructed never to state a number not given to it — the dashboard would
render `issue.trend_change_pct` etc. directly regardless, so the LLM's prose is never
the source of a number, only its explanation (§Open-Question-4 in
PHASE0_ARCHITECTURE.md). A secondary regex-based groundedness check logs (never blocks)
if generated text mentions an unsupported number — see `app/insights/groundedness.py`.
Fully covered by mocked tests (`tests/test_insights.py`) plus a real end-to-end run
against the seeded wait-time issue, which produced a correctly-grounded insight citing
the exact 10→40 (300%) increase from its evidence.

### Recommended actions & human approval (Phase 6)

The core human-in-the-loop loop (§kickoff spec: "AI may recommend. It should not
autonomously execute consequential business decisions."). One issue's full lifecycle:

```
POST /issues/{id}/review                          # free — identified -> reviewed
POST /issues/{id}/actions/recommend                # ONE Claude call (or free template fallback)
                                                    # -> creates an Action, reviewed -> recommended
POST /actions/{id}/submit-for-approval             # free — recommended -> awaiting_approval
POST /actions/{id}/approve  {"decision_note": "..."} # free — awaiting_approval -> approved -> action_created
POST /actions/{id}/resolve                         # free — action_created -> resolved
POST /issues/{id}/monitor                          # free — resolved -> monitoring
POST /issues/{id}/close                            # free — monitoring -> closed
POST /issues/{id}/dismiss  {"reason": "..."}        # free — dismiss from any pre-approval state
GET  /issues/{id}/audit                            # every transition for the issue AND its action(s), merged
```

Only `actions/recommend` costs an API call — every other step is deterministic. All
transitions are validated against a shared state machine (`app/workflow/state_machine.py`)
and logged to `WorkflowEvent` — an invalid transition (e.g. approving an already-rejected
action) returns `409` and is never logged as if it happened. `Action` and `Issue` share
one status vocabulary and are cascaded together by `app/actions/service.py`. An
approver's edit to the AI draft is never destructive: `Action.recommended_text` keeps the
original AI output, and the edit lives separately on `ActionApproval.modified_text`.

Verified live end-to-end against the real seeded Wait Time issue — walked
identified → reviewed → recommended → awaiting_approval → approved → action_created →
resolved → monitoring → closed via real API calls, with the complete, correctly-ordered
audit trail confirmed via `GET /issues/{id}/audit`. Also see `tests/test_workflow.py`
(state-machine graph itself) and `tests/test_actions.py` (full happy path + invalid
transitions, mocked AI call).

### Outcome monitoring (Phase 7)

Fully deterministic — no AI calls anywhere in this phase. Via the API (all auth required):

```
POST /actions/{action_id}/evaluate-outcome     # single action, 409 if not resolved yet
GET  /actions/{action_id}/outcome              # read the last-computed verdict
POST /outcomes/evaluate?business_id=...        # batch — every resolved-or-later action
```

`app/actions/outcome.py` compares negative-mention volume in the 4 weeks immediately
before an action's resolution against the 4 weeks immediately after (excluding the
resolution week itself on both sides — a clean gap, since that week is a mix of
pre/post). The one subtlety this module exists to get right: **"no negative mentions
after" is not the same as "no reviews at all after."** Both look identical if you only
check `negative_count`, so it checks total `mention_count` for the after-period first —
if zero, the verdict is `insufficient_data`, not a misleading `improved`. Verified live
against the real resolved Wait Time action from Phase 6: since it was resolved at
essentially "now" and the synthetic dataset's data ends 2026-08-30, there's genuinely no
after-period data yet, and the system correctly reports `insufficient_data` rather than
fabricating a verdict. The `improved`/`worsened`/`no_significant_change` paths are each
covered by a seeded scenario in `tests/test_outcomes.py`.

### Dashboard (Phase 9)

A Next.js (App Router, TypeScript, Tailwind) frontend under `frontend/`, consuming the
FastAPI backend directly — no server-side rendering of authenticated data (the app is
inherently client-only: a JWT in `localStorage`, no server session), so every dashboard
page is a Client Component and `DashboardShellNoSSR` explicitly disables SSR for the
shared shell to avoid a hydration mismatch against stateless server renders.

```bash
cd frontend
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm install
npm run dev                  # http://localhost:3000 — requires the backend running (docker compose up)
```

Pages: **Overview** (review volume, rating/sentiment/language distributions — business
analytics), **Customer Experience** (top positive/negative aspects), **Issues** (list +
detail with the full evidence/insight/priority-breakdown/audit-trail panel and workflow
buttons wired to the real approve/reject/resolve endpoints), **Actions** (pending
approvals with one-click approve/reject), **System Health** (the `ProcessingRun` table —
deliberately a separate page from the business views, per the architecture's
business-vs-technical split, §9 mentor point 8).

Two small, necessary backend additions this phase (nothing existing exposed
business-wide aggregates or a way to discover which businesses/locations exist at all):
`app/analytics/` (`GET /analytics/overview`, `GET /analytics/aspects`) and
`app/businesses/` (`GET /businesses`, `GET /businesses/{id}/locations`), both read-only.
`GET /actions` also gained a `business_id` filter. All covered by
`tests/test_analytics.py` — literally the Phase 9 DoD wording: every number the
dashboard would show is asserted against a hand-computed source-of-truth query, not
just re-running the same code path.

Verified live in a real browser against the real backend: login, all five pages
rendering real seeded data, the Issue detail page's full evidence/audit-trail panel
(confirmed to exactly match the real Phase 6/7 workflow history), and a live
approve/reject click-through against a throwaway test action (cleaned up afterward) to
confirm the buttons genuinely call the real endpoints, not just render correctly. Zero
console errors after fixing one real hydration-mismatch bug found during that
verification (see `frontend/components/DashboardShellClient.tsx`).

### Scheduled Jobs & Notifications (Phase 10)

`scripts/run_pipeline.py` is the single entrypoint a scheduler runs periodically: it
chains aggregation -> issue detection -> trend/priority recompute -> outcome evaluation,
all deterministic and free. Review analysis and insight generation are the only two
AI-touching stages in the whole system, so they're off by default here and only run if
you explicitly pass `--analyze-limit N` / `--generate-insights --insights-limit N` — a
scheduled job must never silently spend API budget.

```bash
python scripts/run_pipeline.py --business-name "The Local Table"
```

Every call inside it passes `trigger=ProcessingRunTrigger.CRON` instead of the default
`MANUAL`, which is pure audit-trail metadata on `ProcessingRun` — same code path either
way. `tests/test_pipeline.py` asserts a cron-triggered run produces identical results
(status, scope, success count) to an equivalent manually-triggered one on the same
seeded data.

`render.yaml` defines (spec only — actual provisioning is Phase 12) the Render Cron Job
that would run this script daily against the deployed Postgres instance.

Two business events now generate an in-app `Notification` (`app/notifications/`):
a newly-detected high-severity issue (`detect_recurring_issues` in
`app/issues/service.py`) and an action moving to `awaiting_approval`
(`submit_action_for_approval` in `app/actions/service.py`). Re-detecting an
already-known issue does not re-notify — only a brand-new `Issue` row does.
Deterministic throughout, no AI involved.

```
GET  /notifications?business_id=...&unread_only=true
POST /notifications/{notification_id}/read
```

The dashboard header (`frontend/components/NotificationBell.tsx`) polls unread
notifications every 30s, shows an unread-count badge, and links each item to its
issue/action, marking it read on click. Verified live: rebuilt the API image (it had
gone stale mid-session — `GET /notifications` was 404ing against a running container
built before this router existed), seeded one real notification row, confirmed the
badge count, dropdown, and click-through-to-issue-detail with mark-as-read all worked
against the real backend.

### Evaluation Consolidation & Hardening (Phase 11)

All per-phase evaluation code now lives under one documented `evaluation/` package
instead of being scattered across scripts and test files:

- `evaluation/ai_quality.py` — the Phase 3 AI-quality eval (Claude classification
  accuracy against 48 hand-labeled examples), moved here from `scripts/`. It spends one
  real API call per example, so it stays a manual, opt-in run
  (`python scripts/evaluate_ai_analysis.py`, now a thin CLI wrapper around this module)
  — never invoked by pytest or CI. `load_latest_report()` reads the already-committed
  artifact (`data/synthetic/eval_report.json`) for free.
- `evaluation/report.py` — pure, deterministic report-building logic (unit-tested in
  `tests/test_evaluation_report.py` with synthetic inputs — no subprocess, no API, no DB).
- `evaluation/generate_report.py` — the script that actually assembles the report: runs
  the full deterministic pytest suite per marker (free) and reads the AI-quality
  artifact (free, never regenerates it), then writes `evaluation/EVAL_REPORT.md`.

```bash
python evaluation/generate_report.py
```

Current numbers (see [evaluation/EVAL_REPORT.md](evaluation/EVAL_REPORT.md) for the
live-generated version): 75/75 deterministic tests passing across unit/integration
markers; the one-time AI-quality run scored 100% overall-sentiment accuracy, 100%
aspect recall, 100% aspect-sentiment accuracy, and 100% structured-output validity
across all 48 hand-labeled examples and 144 real Claude calls (Phase 3) — no gaps
surfaced that would justify spending further API budget to expand the labeled set.

A pass over the codebase for `TODO`/`FIXME`/stray edge cases found none — every
documented limitation (e.g. `close_issue`'s known re-triage gap, outcome
`insufficient_data` handling) was already an intentional, written-down design decision
from its originating phase, not an oversight; ADR-9 (evaluation built incrementally per
phase, not saved for the end) is why this phase found nothing left to patch.

## Project structure

```
app/
  auth/            single-admin JWT auth (login, seeding, dependency guard)
  ingestion/       review ingestion: validation, idempotent dedup, language detection
  analysis/        Claude structured-output client (shared by insights/ and actions/ too),
                   validation, retry/dead-letter, AIInvocation logging
  aggregation/     deterministic weekly rollups into AggregatePeriodMetric (no AI calls)
  issues/          taxonomy-based recurring-issue promotion, trend detection, explainable
                   priority scoring, IssueEvidence provenance, issue-level workflow steps
  insights/        grounded LLM insight synthesis — evidence snapshot, prompt/tool schema,
                   secondary groundedness check, deterministic-template fallback
  actions/         AI action recommendation (reuses insights/ evidence + analysis/ client),
                   human approval workflow (Action, ActionApproval), and outcome tracking
                   (Outcome) — before/after verdict once an action resolves
  workflow/        shared state-machine validator + WorkflowEvent audit logging, used by
                   both issues/ and actions/
  analytics/       business-analytics read-model for the dashboard (overview, top aspects)
  businesses/      read-only Business/Location discovery (created only via the seed script)
  notifications/   deterministic in-app Notification side-effects of specific business
                   events (new high-severity issue, action awaiting approval)
  models/          SQLAlchemy models (User, ProcessingRun, AIInvocation, WorkflowEvent,
                   Business, Location, Topic, Aspect, Review, ReviewAnalysis, ReviewAspect,
                   AggregatePeriodMetric, Issue, IssueEvidence, Insight, Action,
                   ActionApproval, Outcome, Notification)
  observability/   Sentry init, structured JSON logging, /system-health read API
  core/            shared retry/backoff policy (tenacity)
  taxonomy_seed.py static topic/aspect taxonomy, seeded at startup
  main.py          FastAPI app, CORS, rate limiting, startup seeding
alembic/           migrations
scripts/           dataset generator/loader, run_analysis.py, evaluate_ai_analysis.py,
                   run_aggregation.py, run_pipeline.py (Phase 10 scheduled-job entrypoint)
render.yaml        Render Cron Job spec wrapping run_pipeline.py (Phase 10; provisioned in Phase 12)
evaluation/        consolidated eval harness (Phase 11): AI-quality eval, report builder,
                   generate_report.py, EVAL_REPORT.md
data/synthetic/    generated dataset + eval labels + ground-truth manifest (deterministic output, safe to commit)
tests/             pytest suite (unit/integration/eval/e2e markers); tests/factories.py
                   builds fully-analyzed review fixtures without a live Claude call
frontend/          Next.js dashboard (App Router, TypeScript, Tailwind, Recharts) — see
                   Phase 9 section above for pages and setup
```

Scheduled jobs/notifications, reliability/observability hardening, full evaluation-suite
consolidation, and deployment/CI land in the remaining phases per the phased plan in
[PHASE0_ARCHITECTURE.md](PHASE0_ARCHITECTURE.md). Phase 8 (public review-response
workflow) has been formally dropped from this project's scope.
