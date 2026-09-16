# Step 8.7 to 8.8 Handoff

## Completed boundary

Steps 8.3 through 8.7 expose the persisted football and model projections under
`/api/v1`. Teams and seasons retain canonical UUID and registry checksum
provenance. Fixtures deterministically combine current observations, completed
results and historical fallback revisions. Standings return the latest complete
stored snapshot.

Predictions are immutable stored three-way probabilities only. Simulations and
the predicted table read complete stored summaries and position mass only.
Model performance is explicitly development evidence and reports the latest
append-only registry state truthfully. The actual entry remains
`development_accepted`; no active model exists.

The query boundary is lazy and request-scoped. It selects only the database for
the current environment, starts a read-only transaction, requires exact
migration head and disposes its engine. Production cannot fall back to a local
database. Collection ordering and pagination are deterministic, while missing
resources and database failures use the shared sanitized error envelope.

## Preserved boundaries

- No model, provider or artifact is loaded by importing modules or constructing
  the application.
- No prediction, scoreline distribution, simulation or metric is generated.
- Prediction, simulation and performance queries exclude the sealed 2025–26
  test season; no target or final-test evidence is inspected.
- No registry entry is promoted, activated, retired, rejected or otherwise
  mutated.
- No database row, registry byte, model artifact or raw capture is written.
- Development and test PostgreSQL targets remain explicit and isolated and
  raw-manifest verification remains the mandatory pre-write gate.
- No production provider or artifact corpus, frontend, deployment, automation
  or CI/CD configuration is introduced.

## Verification boundary

Focused unit tests cover the public schemas, all routes, filters, deterministic
projection mapping, read-only transaction guard, exact migration head,
environment selection, registry-state truth and sanitized failure behavior. A
live PostgreSQL integration test calls every collection and available singular
projection against the isolated test target and verifies relevant table counts
and artifact bytes remain unchanged.

The complete Python 3.14.7 quality suite passes 552 tests with 90.58% branch
coverage. Both local databases remain at `f0009_step_7_9`, the
historical raw-data manifest remains verified and the actual registry continues
to resolve to `no_active_model`.

## Step 8.8 boundary

Step 8.8 may enable and review the generated OpenAPI document and add explicit
schema/operation contract snapshots for the endpoints already implemented. It
must not add new football resources, change query semantics, execute workflows,
contact a provider, inspect sealed targets, mutate registry state or begin
security, deployment, frontend, automation or CI/CD work.
