# Implementation Roadmap

This is the durable implementation sequence for the Premier League prediction
platform. The master roadmap supplied by the user controls milestone and step
numbering. Status annotations describe the repository as implemented, including
work completed ahead of an earlier unfinished step.

Two standing project decisions intentionally override the original wording:

- the supported runtime is 64-bit Python 3.14.7, not Python 3.13; and
- GitHub Actions and other CI/CD automation are excluded unless the user
  explicitly reverses that decision.

Each numbered step should remain small enough to review and test in isolation.

## Milestone A — Repository Foundation — complete

- **Step 0.1 — complete:** Create repository hygiene and the documentation
  skeleton.
- **Step 0.2 — complete with approved runtime revision:** Select 64-bit Python
  3.14.7 and create the local environment.
- **Step 0.3 — complete:** Add `pyproject.toml`, pinned dependency groups, and
  local quality tools.
- **Step 0.4 — complete:** Create the application package and smoke test.
- **Step 0.5 — complete with approved CI exclusion:** Add typed configuration,
  `.env.example`, and structured logging. CI was deliberately not added.

## Milestone B — Historical Data System — complete

- **Step 1.1 — complete:** Define source and raw-file manifests.
- **Step 1.2 — complete:** Implement the Football-Data downloader, initially for
  one season and subsequently supporting the complete manifest.
- **Step 1.3 — complete:** Verify checksums and enforce immutable raw storage.
- **Step 1.4 — complete:** Parse Football-Data CSV into a typed source schema.
- **Step 1.5 — complete:** Define the provider-independent canonical fixture
  schema.
- **Step 1.6 — complete:** Add canonical teams and explicit source alias
  mappings without fuzzy matching.
- **Step 1.7 — complete:** Normalize one season, then expand deterministic
  materialization to 2015–16 through 2025–26.
- **Step 1.8 — complete:** Add duplicate, score, date, status, identity, and
  competition-wide season validation.
- **Step 1.9 — complete:** Handle missing columns and postponed fixtures, and
  record reviewed promoted-team membership.

## Milestone C — Point-in-Time Features and Elo — in progress

- **Step 2.1 — complete:** Define the versioned, provider-independent feature
  schema and metadata, with fixture, season, and team identity; kickoff and
  precision; feature cutoff; structurally separate predictors and labels; and
  source/schema provenance.
- **Step 2.2 — complete:** Implement deterministic chronological match-state
  construction, including conservative simultaneous batches for local dates
  containing date-only fixtures.
- **Step 2.3 — complete:** Add shifted season-to-date and recent-form features
  calculated only from prior completed batches.
- **Step 2.4 — complete:** Add home/away and rest/congestion features. The
  implementation also includes prior-only goal, shot, foul, card, promotion,
  and season-progress context.
- **Step 2.5 — next:** Add explicit season-opening priors. The current predictor
  schema resets state at each season boundary and deliberately has no
  cross-season carryover, so this requires a reviewed semantic and
  schema-version decision.
- **Step 2.6 — pending:** Implement Elo initialization, pre-match prediction,
  and post-batch update, including home advantage and season transitions.
- **Step 2.7 — partially complete:** Feature leakage, determinism, missing-data,
  checksum, and temporal-boundary tests are complete. Add adversarial invariants
  for season-opening priors and Elo when Steps 2.5 and 2.6 are implemented.
- **Step 2.8 — complete ahead of Steps 2.5–2.7:** Produce the first reproducible
  training dataset from all 11 verified feature seasons, with a versioned row
  contract, structurally separate target, deterministic bytes, and complete
  checksum provenance.

Milestone C is not complete until Steps 2.5, 2.6, and the remaining Step 2.7
coverage are finished and the training dataset is regenerated if its approved
predictor schema changes.

## Milestone D — Probabilistic Models — planned

- **Step 3.1:** Implement naive and Elo benchmarks.
- **Step 3.2:** Train multinomial logistic regression.
- **Step 3.3:** Implement expanding/walk-forward validation.
- **Step 3.4:** Freeze an untouched test season.
- **Step 3.5:** Train and tune CatBoost within temporal folds.
- **Step 3.6:** Assess and apply probability calibration.
- **Step 3.7:** Implement a Poisson score baseline.
- **Step 3.8:** Implement and test the Dixon–Coles adjustment.
- **Step 3.9:** Compare models against predefined acceptance gates.
- **Step 3.10:** Add explanation data appropriate to each model.

## Milestone E — Registry and Simulation — planned

- **Step 4.1:** Define artifact layout and manifest schema.
- **Step 4.2:** Serialize, checksum, and reload models.
- **Step 4.3:** Implement model registry states and promotion rules.
- **Step 4.4:** Define simulator domain structures.
- **Step 4.5:** Sample deterministic scorelines.
- **Step 4.6:** Implement table updates and ranking.
- **Step 4.7:** Vectorize 10,000 simulations.
- **Step 4.8:** Aggregate threshold and position probabilities.
- **Step 4.9:** Add simulator invariant and reproducibility tests.

## Milestone F — PostgreSQL Persistence — planned

- **Step 5.1:** Finalize the entity-relationship model against produced data.
- **Step 5.2:** Configure local and test PostgreSQL connections.
- **Step 5.3:** Initialize Alembic.
- **Step 5.4:** Add identity, season, and fixture migrations.
- **Step 5.5:** Add rating, feature, and model migrations.
- **Step 5.6:** Add prediction and evaluation migrations.
- **Step 5.7:** Add simulation and ingestion/cache migrations.
- **Step 5.8:** Implement repositories one aggregate at a time.
- **Step 5.9:** Add transaction and PostgreSQL integration tests.

## Milestone G — Current-Season Integration — planned

- **Step 6.1:** Define provider capability and domain contracts.
- **Step 6.2:** Implement fixture/team adapter transformation.
- **Step 6.3:** Add quota handling, retries, and sanitized logging.
- **Step 6.4:** Add PostgreSQL response caching.
- **Step 6.5:** Synchronize fixtures idempotently.
- **Step 6.6:** Reconcile completed results.
- **Step 6.7:** Synchronize standings.
- **Step 6.8:** Add squads and players only after match ingestion passes.
- **Step 6.9:** Add recorded-response contract tests.

## Milestone H — Prediction Lifecycle — planned

- **Step 7.1:** Load the active model deterministically.
- **Step 7.2:** Generate upcoming-match features.
- **Step 7.3:** Persist immutable predictions.
- **Step 7.4:** Evaluate completed predictions.
- **Step 7.5:** Update Elo and team state exactly once.
- **Step 7.6:** Regenerate affected future predictions.
- **Step 7.7:** Regenerate season simulations.
- **Step 7.8:** Make the complete post-match workflow idempotent.
- **Step 7.9:** Add recovery and partial-failure tests.

## Milestone I — FastAPI — planned

- **Step 8.1:** Create the app factory and health endpoints.
- **Step 8.2:** Add error envelopes, pagination, and request IDs.
- **Step 8.3:** Implement teams and seasons.
- **Step 8.4:** Implement fixtures and standings.
- **Step 8.5:** Implement predictions.
- **Step 8.6:** Implement simulations and the predicted table.
- **Step 8.7:** Implement model metrics and performance.
- **Step 8.8:** Add OpenAPI and API contract tests.
- **Step 8.9:** Add CORS, security headers, and rate controls.

## Milestone J — Live Data, Automation, and Retraining — planned

- **Step 9.1:** Implement cache-aware live fixture reads.
- **Step 9.2:** Add a kickoff-aware polling policy.
- **Step 9.3:** Add final-match reconciliation.
- **Step 9.4:** Expose safe job CLI commands.
- **Step 9.5 — excluded under the current user constraint:** Add scheduled
  GitHub Actions workflows only if the user explicitly reverses the no-CI/CD
  decision. Do not implement substitute CI/CD configuration implicitly.
- **Step 9.6:** Build the candidate retraining workflow.
- **Step 9.7:** Add an explicit model comparison and promotion report.
- **Step 9.8:** Add monitoring and operational documentation.

## Milestone K — Backend Release — planned

- **Step 10.1:** Harden tests, migrations, and dependency scanning.
- **Step 10.2:** Create production container/runtime configuration.
- **Step 10.3:** Provision and migrate a hosted PostgreSQL database.
- **Step 10.4:** Deploy FastAPI after current platform research and explicit
  deployment approval.
- **Step 10.5:** Run historical-to-API end-to-end validation.
- **Step 10.6:** Verify secret handling, quotas, recovery, and reproducibility.
- **Step 10.7:** Declare the backend/ML acceptance gate passed.

## Milestone L — Frontend, Last — planned

- **Step 11.1:** Reassess and document the frontend architecture.
- **Step 11.2:** Initialize Next.js/TypeScript and a generated API client.
- **Step 11.3:** Build the dashboard and navigation.
- **Step 11.4:** Build fixtures and match-prediction views.
- **Step 11.5:** Build teams and squads.
- **Step 11.6:** Build actual and predicted standings.
- **Step 11.7:** Build simulation visualization.
- **Step 11.8:** Build history and model-performance views.
- **Step 11.9:** Build the near-live match centre.
- **Step 11.10:** Add accessibility, component, and end-to-end tests.
- **Step 11.11:** Deploy the frontend.
- **Step 11.12:** Run full production integration tests.

## Milestone completion rule

A milestone is complete only when its implementation and documentation agree,
the complete local quality suite passes, generated artifacts are reproducible,
important constraints are recorded, and a local milestone commit is created.
