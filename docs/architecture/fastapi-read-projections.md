# FastAPI Read Projections

## Scope

Steps 8.3 through 8.7 add version-one, read-only resource routes for teams,
seasons, fixtures, standings, predictions, persisted simulations and model
development performance. They reuse the Step 8.2 request-ID, error and
pagination contracts and perform no workflow command, provider request,
artifact load or registry mutation.

All routes are under `/api/v1`:

- `GET /teams` and `GET /teams/{team_id}`;
- `GET /seasons` and `GET /seasons/{season_id}`;
- `GET /fixtures` and `GET /fixtures/{fixture_id}`;
- `GET /seasons/{season_id}/standings`;
- `GET /predictions` and `GET /predictions/{prediction_id}`;
- `GET /simulations`, `GET /simulations/{simulation_id}` and
  `GET /simulations/{simulation_id}/predicted-table`; and
- `GET /models` and `GET /models/{model_id}/performance`.

Step 8.8 now publishes these paths at `/openapi.json`, serves Swagger UI at
`/docs` and pins their operation and schema contract without adding a mutating
operation.

## Query boundary

The application factory constructs only a typed query-service object. It does
not create an engine or open a connection. Each request explicitly selects the
test database in the test environment and the development database otherwise;
production fails closed because no production target exists. A request opens a
short transaction, marks it read-only before any resource query, verifies exact
Alembic head `f0009_step_7_9`, executes deterministic selects and disposes the
lazy engine.

Every collection uses the shared offset page and a complete count. Ordering is
stable and ends in canonical identity fields. Registry-backed names and season
metadata select the highest schema version, then checksum, so selection is
deterministic even though registry documents are immutable revisions rather
than mutable current rows.

Fixtures prefer the latest current observation, with checksum tie-breaking,
and fall back to the deterministically selected canonical historical revision.
A persisted current result exposes the fixture as finished with its stored
score and outcome. Standings return only the latest complete persisted snapshot
by retrieval time and checksum. Missing singular resources use stable typed
404 codes; unavailable or incompatible PostgreSQL uses sanitized 503 codes.

## Prediction and simulation safety

Prediction routes select only rows already present in
`prediction.current_model_prediction`. They do not resolve or load a model and
cannot create a feature or prediction. The response includes only the stored
three-way probabilities; no scoreline distribution is inferred.

Simulation routes require an already-persisted run and complete summary. The
predicted table sorts stored expected points, goal difference and goals for,
then team UUID and returns persisted threshold and position probabilities. It
does not execute sampling, build scoreline inputs or regenerate a simulation.

Prediction and simulation queries explicitly exclude season `2025-2026`.
They neither inspect its sealed targets nor produce final-test evidence.

## Development performance and registry truth

Model responses join semantic models to their persisted development assessment
and derive registry state only from the latest append-only database event.
`development_accepted` is returned as that exact state and is never presented
as active. The actual filesystem registry remains unchanged and still has no
active model.

Performance detail contains only persisted evaluation metrics reached through
the model assessment's source evaluations. Its response is explicitly scoped
to `development`; any evaluation dataset using the sealed season in a
non-excluded role is filtered out. The API does not calculate a metric, read a
test target or create promotion evidence.

## Preserved boundaries

Historical raw-manifest verification remains mandatory for repository writes;
these routes introduce no write path and do not weaken that gate. No provider
is selected or contacted. The production artifact corpus is not imported or
modified. No credential, database URL, exception detail or filesystem path is
returned. Step 8.9 adds the separately documented CORS, security-header and
rate-control boundary. Deployment, automation, frontend work and CI/CD remain
outside this boundary.
