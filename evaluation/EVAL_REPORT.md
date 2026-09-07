# Evaluation Report

Generated: 2026-09-07T16:00:12.318522+00:00

## Deterministic test suite

Every non-AI code path (ingestion, aggregation, issue detection, trend/priority, workflow, outcomes, notifications, pipeline orchestration, API routes) is covered by pytest and is fully reproducible — no API cost, safe to run in CI on every commit.

| Marker | Passed | Failed | Total |
|---|---|---|---|
| unit | 33 | 0 | 33 |
| integration | 42 | 0 | 42 |
| e2e | 0 | 0 | 0 |
| **total** | **75** | **0** | **75** |

**Result: PASSING**

## AI quality evaluation

Measures Claude's classification quality against 48 hand-labeled examples (data/synthetic/eval_labels.json) — a one-time real-API run, not re-executed on every commit, per the project's API budget constraint (ADR-9: evaluation built incrementally per phase).

| Metric | Value |
|---|---|
| Examples scored | 48 / 48 |
| Overall sentiment accuracy | 100.0% |
| Aspect recall | 100.0% |
| Aspect-sentiment accuracy | 100.0% |
| Structured-output validity rate | 100.0% |
| Total AI calls made in that run | 144 |
