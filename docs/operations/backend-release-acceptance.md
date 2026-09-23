# Backend Release Acceptance

## Scope

Milestone K Steps 10.5 and 10.6 add deterministic release evidence; they do not
load the production corpus or change the deployed service. The validation uses
the real 2024–25 local historical artifacts only inside an outer transaction on
`pl_platform_test`. It never reads 2025–26 target values, writes Neon, changes
the filesystem registry, contacts a data provider, generates a prediction or
runs a simulation.

## Historical-to-API validation

The release-only integration test performs this complete path:

1. Verify the existing raw manifest entry and exact raw CSV, team registry,
   season registry, canonical manifest and canonical fixture checksums.
2. Project the reviewed 2024–25 season, its 20 members and all 380 canonical
   fixtures into an outer test-database transaction.
3. Force every deferred provenance, completeness and chronology constraint.
4. Read teams, the season detail and filtered/paginated fixtures through the
   production PostgreSQL query service and FastAPI router.
5. Confirm predictions and simulations remain empty rather than manufacturing
   evidence that does not exist.
6. Repeat every HTTP read and require byte-identical response bodies.
7. Roll back the outer transaction and require the database counts and artifact
   tree to match their pre-test state.

This path exposed a stale `is_complete` column reference in the original
canonical-dataset validator. Revision `f0010_step_10_5` repairs only that
function to use the final `completed` season column. It adds no table, data or
privilege. The local development and test databases are upgraded to this head;
the hosted database remains at the last published `f0009_step_7_9` release
until a reviewed commit is published and the production migration and Render
deploy can be coordinated.

## Secret handling

- `.env` and `.env.*` remain Git-ignored, except the non-secret example.
- The Docker context remains deny-by-default and includes only source and
  reviewed build metadata.
- `render.yaml` contains no connection URL, password or migration credential.
- Exactly seven Render variables are permitted: environment, log level, the
  runtime-only pooled database URL prompt, connection timeout, pool size,
  overflow and the trusted Render edge header.
- The privileged direct migration URL remains manual and local. It is never an
  image layer, build argument or Render setting.
- Any credential exposed during the earlier dashboard setup was revoked before
  the final runtime credential was installed.

## Quota and capacity boundaries

Render remains one Free Singapore instance with automatic deployment off.
Neon remains on its Free plan. The single Uvicorn worker uses a pool size of two
and overflow of one, with a ten-second connection timeout. The HTTP limiter
retains its bounded default of 120 requests per 60 seconds and at most 10,000
tracked clients. Provider requests retain conservative quota exhaustion: no
call is retried before the later of the declared reset and retry interval.

Free-service sleep and cold-start latency remain accepted. Do not add keep-
alive traffic, a scheduler or another automation to consume quota or defeat
scale-to-zero behavior.

## Recovery checks

- A database connection failure produces a sanitized HTTP 503 boundary; a
  later request constructs a fresh engine and succeeds after the dependency
  recovers.
- Rate-limit and provider-quota tests prove recovery only after their bounded
  windows reset.
- Post-match workflow tests retain exact retry behavior after child-write and
  event-acknowledgement loss, without double application.
- Runtime database credential recovery is manual: rotate `pl_api` in Neon,
  replace the single Render secret, manually deploy the reviewed revision,
  verify readiness, then revoke the displaced credential.
- Application rollback is manual from Render to a previously verified commit.
  Database downgrade is not a service rollback mechanism and must not be run
  against retained hosted data.

## Reproducibility commands

Run focused acceptance while iterating:

```powershell
pytest --require-local-release tests/integration/api/test_historical_e2e.py
pytest tests/unit/api/test_render_deployment.py tests/unit/api/test_queries.py
```

Run the complete release gate once before closeout:

```powershell
ruff check .
ruff format --check .
mypy src tests migrations
python -m pip check
pytest --cov --require-local-release
git diff --check
```

The actual registry must still contain one `development_accepted` entry and no
active entry after every command. The production readiness response therefore
remains intentionally not ready until a separately authorized lifecycle step.

## Verified result

The complete local gate passes on Python 3.14.7: 669 tests with no skips and
91.12% branch coverage, Ruff lint and formatting across 287 files, strict mypy
across 232 source/test/migration files and dependency consistency. The full
rollback-only migration cycle covers all ten revisions through
`f0010_step_10_5`. The only test warning is the existing Starlette `TestClient`
deprecation emitted by a pinned dependency.
