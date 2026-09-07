# Deployment Readiness

This project has **not been deployed to any cloud platform.** There is no live URL, and
nothing in this repository claims otherwise. What follows is the actual readiness state —
what's already protected, what's safe about the public repository itself, what's required
before a real deployment, and what's deliberately deferred and why — rather than a vague
"production-ready" claim.

## Already protected (implemented and verified)

- **Authentication** — single-admin JWT (bcrypt-hashed password, `PyJWT`), every business
  endpoint gated behind it except `POST /auth/login` itself.
- **Login hardening** — rate-limited (10/min via `slowapi`), and the "wrong password" and
  "no such user" errors are identical, so the endpoint can't be used to enumerate accounts.
- **CORS** — explicit origin allow-list from `CORS_ALLOWED_ORIGINS`, never a wildcard.
- **Input validation** — every write path goes through Pydantic field constraints (length
  caps, rating ranges, id lengths) before touching the database.
- **SQL injection surface** — zero raw/string-interpolated SQL anywhere in `app/`; every
  query goes through SQLAlchemy's parameterized query builder.
- **Idempotent ingestion** — content-hash + `source_review_id` dedup, safe to re-post the
  same batch without creating duplicates.
- **Retry/backoff** — `tenacity`-based bounded retries on Claude calls, classified
  transient (retry) vs. permanent (dead-letter) failure.
- **Batch failure isolation** — one bad review in a batch never rolls back or crashes the
  rest; per-item try/except, per-item commit.
- **Safe error responses** — no `debug=True`, no custom handler that echoes tracebacks;
  unhandled exceptions return a generic 500, never internal detail.
- **Secrets from environment only** — nothing reads a secret from a committed file;
  `Settings` (`app/config.py`) sources everything from env vars, with no real default for
  any actual secret.
- **`.env` protection** — gitignored, confirmed never part of this repository's git history
  (verified before the repo was ever made public — see the audit note below).
- **`.dockerignore`** — added during the pre-publish audit after discovering the Dockerfile's
  `COPY . .` was baking the real local `.env` into the built image's filesystem. Fixed and
  verified: the image no longer contains it, while the app still receives secrets correctly
  through docker-compose's runtime `env_file` injection.
- **No secrets in git** — the entire repository (tracked files and the full commit history)
  was searched for API keys, tokens, passwords, and private-key blocks before the first push.
  None found.
- **Audit trail** — every `Issue`/`Action` state transition is recorded as a `WorkflowEvent`
  (actor, from-state, to-state, reason, timestamp), independent of the AI call log.
- **Sentry** — wired in and opt-in; a no-op when `SENTRY_DSN` isn't set, so "not configured"
  is a normal supported state, not a degraded one.

## Safe for a public repository

- No PII anywhere — the synthetic dataset (`data/synthetic/`) is deterministically generated
  (fixed seed) with no real names, emails, or phone numbers; reviews are text + rating +
  timestamp only.
- No secrets in any tracked file, config file, script, test, or generated artifact.
- CI (`.github/workflows/ci.yml`) uses dummy, clearly-fake credentials — safe to be public.
- The one real Anthropic API key that ever existed for this project lived only in a local,
  gitignored `.env` and was never committed.

## Required before a real deployment

- **Generate real random secrets.** `JWT_SECRET` and `ADMIN_PASSWORD` currently default to
  `change-me-in-env` for local convenience — `.env.example` says to change both, but nothing
  currently *enforces* it. Set real values via the hosting platform's env var/secrets
  manager, never the defaults.
- **Extend `render.yaml`.** It currently defines the scheduled pipeline cron job and the
  managed Postgres database (Phase 10 scope) but not the API web service itself or its full
  env var list (`JWT_SECRET`, `ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`, `CORS_ALLOWED_ORIGINS`,
  `SENTRY_DSN`) — that block gets added when deployment actually happens.
- **Frontend deployment config.** The dashboard (`frontend/`) has no Vercel project yet;
  `NEXT_PUBLIC_API_BASE_URL` needs to point at the deployed API's real URL.
- **Consider a startup guard** that refuses to boot with the default `JWT_SECRET`/
  `ADMIN_PASSWORD` outside `ENV=development`, rather than relying on operator discipline.

## Deliberately deferred (acceptable for this project, not gaps)

- **No RBAC** — single-admin JWT only. This is ADR-5 in [ARCHITECTURE.md](ARCHITECTURE.md):
  the approval workflow needs *an* authenticated actor, not a permission hierarchy, for a
  single-tenant portfolio demo.
- **Rate limiting only on `/auth/login`.** Every other route is already auth-gated with no
  public write surface; broader per-route limits would matter for a genuine multi-tenant
  service, not this one.
- **No explicit request-body size cap** on `POST /reviews/batch` beyond ASGI/Uvicorn
  defaults — low risk given every route requires a valid JWT.
- **In-memory rate limiting**, not Redis-backed — correct for a single process; would need
  a distributed store only once a multi-instance deployment exists to justify it.

## Verification performed

- Full repository scan for secrets (API keys, tokens, passwords, private-key blocks) across
  every tracked and intended-to-be-tracked file — clean.
- Confirmed no `.git` history existed before the audit (this repository's first commit *is*
  its only commit at the time of the public push), so there was nothing prior history could
  have leaked.
- `docker compose exec api` inspection, before and after the `.dockerignore` fix, confirming
  the real `.env` was removed from the built image while the running app still received its
  secrets correctly.
- `ruff check .`, `pytest -q` (75/75), `alembic check`, frontend `tsc --noEmit`, `eslint`,
  and `npm run build` all run clean immediately before the public push.
- Post-push verification: repository visibility confirmed `PUBLIC` via the GitHub API,
  `.env` confirmed absent (404) from the pushed tree, root file listing matched exactly
  what was intended, README confirmed rendering correctly, and CI passed on the first push.
