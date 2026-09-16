# Implementation Roadmap

This is the durable implementation sequence for the Premier League prediction
platform. The master roadmap supplied by the user controls milestone and step
numbering. Status annotations describe the repository as implemented, including
the two approved deviations recorded below.

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
- **Step 0.3 — complete:** Add `pyproject.toml`, pinned dependency groups and
  local quality tools.
- **Step 0.4 — complete:** Create the application package and smoke test.
- **Step 0.5 — complete with approved CI exclusion:** Add typed configuration,
  `.env.example` and structured logging. CI was deliberately not added.

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
- **Step 1.8 — complete:** Add duplicate, score, date, status, identity and
  competition-wide season validation.
- **Step 1.9 — complete:** Handle missing columns and postponed fixtures and
  record reviewed promoted-team membership.

## Milestone C — Point-in-Time Features and Elo — complete

- **Step 2.1 — complete:** Define the versioned, provider-independent feature
  schema and metadata, with fixture, season and team identity; kickoff and
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
- **Step 2.5 — complete:** Add explicit season-opening priors. Continuing clubs
  use their immediately preceding Premier League season, promoted clubs use the
  preceding league aggregate and the first tracked season uses a fixed neutral
  baseline. Blend these with observed current-season results using a five-match
  prior weight.
- **Step 2.6 — complete:** Implement Elo initialization, pre-match prediction,
  and post-batch update with a 1500 baseline, 65-point home advantage, K-factor
  20, 400-point scale and 75% offseason retention for continuing clubs.
- **Step 2.7 — complete:** Add adversarial leakage, determinism, missing-data,
  checksum, temporal-boundary, opening-prior, Elo transition and simultaneous
  batch tests.
- **Step 2.8 — complete:** Regenerate the reproducible 11-season training
  dataset using predictor schema version 2, structurally separate targets,
  deterministic bytes and the complete historical checksum chain.

## Milestone D — Probabilistic Models — complete

- **Step 3.1 — complete:** Implement deterministic three-way naive and Elo
  benchmarks against a fixed chronological holdout.
- **Step 3.2 — complete:** Train deterministic L2-regularized multinomial
  logistic regression using training-window-only preprocessing.
- **Step 3.3 — complete:** Implement five expanding-season walk-forward folds
  through 2024–25 and aggregate probabilistic metrics.
- **Step 3.4 — complete:** Freeze 2025–26 as a target-free, checksum-pinned
  untouched test identity and policy artifact. It remains unconsumed by model
  fitting, tuning, selection, calibration, acceptance and metrics.
- **Step 3.5 — complete:** Evaluate three predefined deterministic CatBoost
  candidates within the five expanding development folds, select by proper
  probabilistic scores and fit the winner on all development seasons without
  serializing it or opening the untouched test target.
- **Step 3.6 — complete:** Assess bounded scalar temperature scaling with four
  expanding prior-out-of-fold calibration folds. The paired development result
  selects the identity policy because temperature scaling did not improve the
  proper probabilistic scores; the untouched test remains sealed.
- **Step 3.7 — complete:** Implement a deterministic L2-regularized independent
  Poisson team attack/defence and home-advantage score baseline, evaluated over
  the five established chronological folds.
- **Step 3.8 — complete:** Fit and test a training-window-only Dixon–Coles rho
  correction for the four low-score cells and compare its three-way projection
  over the same folds.
- **Step 3.9 — complete:** Apply frozen coverage, proper-score improvement and
  fold-stability gates to identical five-fold development populations, then
  select the accepted champion deterministically.
- **Step 3.10 — complete:** Add deterministic global explanation data using
  standardized logistic coefficients, CatBoost structural importance,
  canonical-team Poisson rate components and Dixon–Coles correction scope.

## Milestone E — Registry and Simulation — complete

- **Step 4.1 — complete:** Define deterministic artifact layout, stable
  identities, strict manifest contracts and fail-closed compatibility rules.
- **Step 4.2 — complete:** Serialize CatBoost and its stateless preprocessor as
  canonical checksum-pinned components and verify deterministic reload behavior.
- **Step 4.3 — complete:** Implement an append-only local registry,
  development-acceptance promotion and fail-closed active-promotion boundary.
- **Step 4.4 — complete:** Define strict simulator inputs, scoreline
  distributions, sampled results, fixture batches and table-state contracts.
- **Step 4.5 — complete:** Sample scorelines with stateless, order-independent
  SHA-256 draws and canonical inverse-CDF selection.
- **Step 4.6 — complete:** Implement immutable table updates and official
  statistical ranking with fail-closed unresolved-playoff handling.
- **Step 4.7 — complete:** Execute exactly 10,000 simulations with vectorized
  inverse-CDF score sampling, table arithmetic and final-position mass.
- **Step 4.8 — complete:** Aggregate expected table values, all 20 position
  probabilities and champion, top-four, top-six and relegation thresholds.
- **Step 4.9 — complete:** Verify exact reproducibility, sampling behavior,
  table conservation and league-wide probability invariants.

**Closeout evidence:** The complete local suite passes with 343 tests and
90.86% branch coverage. Ruff lint, Ruff formatting, strict mypy and dependency
consistency checks also pass. The 2025–26 target remained sealed and no model
was activated.

## Milestone F — PostgreSQL Persistence — complete

- **Step 5.1 — complete:** Finalized the PostgreSQL entity-relationship model
  against produced data and artifacts. Stable UUID/content identities, exact
  bytes, ordering, provenance, metadata separation, append-only lifecycle,
  simulation semantics, ownership and fail-closed constraints are fixed without
  database configuration, Alembic or migrations.
- **Step 5.2 — complete:** Configured secret-safe, typed and explicitly
  isolated local/test PostgreSQL connections through a restricted application
  login, with a read-only fail-closed connectivity check.
- **Step 5.3 — complete:** Initialized a URL-free Alembic environment with
  explicit development/test selection, production rejection and no schema
  revision or database object.
- **Step 5.4 — complete:** Added checked domains, exact-content lineage,
  identity/reference, season and canonical-fixture migrations.
- **Step 5.5 — complete:** Added predictor schema, feature/Elo, semantic-model,
  artifact-component and append-only registry migrations.
- **Step 5.6 — complete:** Added training, sealed-test, chronological prediction
  and evaluation migrations.
- **Step 5.7 — complete:** Added raw-capture, future provider-cache, explicit
  scoreline-distribution, simulation-input/run and aggregate-summary migrations.
- **Step 5.8 — complete:** Implemented the typed, raw-manifest-gated immutable
  aggregate repository with exact-byte-first atomic writes, dependency-ordered
  projections, idempotent reload comparison and stable failure categories.
- **Step 5.9 — complete:** Added live PostgreSQL transaction, rollback,
  idempotency, conflict, checksum, immutable-guard and migration-contract tests.

**Closeout evidence:** Commit `22e595a` closes the implementation. The complete
Python 3.14.7 suite passes with 389 tests and 90.53% branch coverage. Ruff lint,
Ruff formatting, strict mypy, dependency consistency, whitespace and local
Markdown-link checks pass. PostgreSQL 18.4 development and test targets connect
as restricted `pl_app` in UTC, complete clean base-to-head migration cycles and
end at `f0004_step_5_7` with zero application rows. Raw-manifest verification
passes for all 11 captures. No production corpus was imported, the 2025–26
target remained sealed, no final-test metric was calculated, no scoreline was
inferred from classifier probabilities and no model was activated.

## Milestone G — Current-Season Integration — complete

- **Step 6.1 — complete:** Defined provider-neutral capability declarations,
  explicit provider identities, strict team/fixture/status/result/standings
  payloads, UTC and date-only chronology, completion rules, field governance,
  typed pagination/quota/metadata/errors and an exact-byte provider-cache fit
  without selecting a provider or performing I/O.
- **Step 6.2 — complete:** Added pure fixture/team transformations using only
  reviewed exact aliases or external IDs, stable canonical fixture UUIDs,
  complete capture provenance and provider-local date-only batching.
- **Step 6.3 — complete:** Added credential-free allowlisted HTTPS request
  specifications, secret-header authentication, redirect-disabled transport,
  conservative quota gating, bounded deterministic retries and sanitized logs.
- **Step 6.4 — complete:** Added raw-manifest-gated immutable PostgreSQL cache
  writes and latest-fresh reads preserving exact request/response bytes,
  checksums, retrieval time, compatibility and transport metadata.
- **Step 6.5 — complete:** Added content-derived fixture revisions, exact
  provider-reference mappings, cache-provenanced observations and validated
  simultaneous batches with idempotent raw-manifest-gated persistence.
- **Step 6.6 — complete:** Added exact team/fixture resolution and an immutable
  one-result-per-fixture ledger with score/outcome, completion and prior-state
  consistency checks.
- **Step 6.7 — complete:** Added complete 20-team standings snapshots with
  separate provider-team references and point-in-time reconciliation against
  the official result ledger.
- **Step 6.8 — complete:** Added optional provider-neutral players and squads,
  reviewed exact player resolution, explicit registration/transfer/loan
  chronology, complete simultaneous 20-team snapshots and immutable
  exact-cache-provenanced persistence.
- **Step 6.9 — complete:** Added a credential-free recorded-response manifest
  and exact-byte replay tests for every declared capability, with fail-closed
  checksum, request-identity, compatibility, path and capability validation.

**Closeout evidence:** On Python 3.14.7, all 460 tests pass with 90.50% branch
coverage. Ruff lint and formatting, strict mypy across 148 Python files,
dependency consistency, diff whitespace and local Markdown-link checks pass.
PostgreSQL 18.4 development and test databases connect as restricted `pl_app`
in UTC and end at exact head `f0006_step_6_8`; the test database completed the
`f0006` downgrade/re-upgrade cycle. The recordings are synthetic, no provider
was selected or contacted and no production data or model artifact was
imported. The historical manifest gate remained active, the 2025–26 target
remained sealed and no model was activated.

**Implementation commit:** `f34c349` — complete current-season integration.

## Milestone H — Prediction Lifecycle — complete

- **Step 7.1 — complete:** Implemented a strict read-only active-model boundary
  that deterministically verifies all append-only registry histories, requires
  exactly one explicitly `active` entry and validates the registry, manifest,
  component, provenance, runtime, preprocessor, predictor, outcome, calibration
  and CatBoost depth-6 chain before returning a loaded model. Stable typed
  failures cover absent or ambiguous active state and every incompatible or
  incomplete layer. Synthetic active snapshots verify successful loading while
  the actual registry remains `development_accepted` and returns
  `no_active_model`.
- **Step 7.2 — complete:** Generates deterministic unlabeled predictor-schema-v2
  rows from synchronized current fixture and completed-result evidence, with
  retrieval-time cutoffs, conservative simultaneous batches, exact state/prior/
  Elo checksums and no persisted team-state mutation.
- **Step 7.3 — complete:** Generates three-way probabilities only through an
  explicitly active Step 7.1 model and persists immutable exact-byte predictions
  with complete feature, registry-event, model, artifact and manifest lineage.
  The actual no-active registry remains fail-closed; synthetic active fixtures
  cover the successful path.
- **Step 7.4 — complete:** Evaluates immutable predictions only after matching
  official completed-result evidence, storing deterministic per-fixture natural-
  log loss, multiclass Brier score and normalized ranked probability score.
  The frozen 2025–26 season is explicitly prohibited.
- **Step 7.5 — complete:** Advances one official simultaneous result batch into
  an append-only operational result/Elo snapshot. Immutable evaluation lineage,
  deterministic pre/post identities and database uniqueness prevent a result
  from being applied twice or a state predecessor from forking.
- **Step 7.6 — complete:** Regenerates only future predictions whose prior
  feature state omitted the applied result batch. Replacement features and
  active-model predictions are new immutable records with explicit supersession
  lineage; prior records remain unchanged.
- **Step 7.7 — complete:** Regenerates deterministic 10,000-run season
  simulations from the advanced completed ledger and independently approved
  explicit scoreline distributions. Exact NumPy components, summaries and the
  prior/replacement run relationship are retained without deriving scorelines
  from CatBoost probabilities.
- **Step 7.8 — complete:** Composes evaluation, state advancement, affected
  prediction regeneration and simulation regeneration under one canonical
  workflow identity. Append-only, hash-linked checkpoint history makes an
  identical retry a verified no-op and never replaces a mutable status row.
- **Step 7.9 — complete:** Covers child-write and journal-acknowledgement crash
  windows at every stage, malformed/gapped history, payload conflicts and
  completed-workflow retry behavior. Recovery resumes only the missing suffix.

**Milestone H closeout:** Python 3.14.7 completed 520 tests with 90.13%
branch-aware coverage. Ruff lint/format, strict mypy over 177 Python files and
dependency consistency passed. Both isolated PostgreSQL databases are at
`f0009_step_7_9`; the test database passed the `f0009` to `f0008` downgrade and
re-upgrade cycle. The actual registry still resolves to `no_active_model`.

**Implementation commit:** `4b44fcd` — add resumable idempotent post-match
workflow journal.

## Milestone I — FastAPI — in progress

- **Step 8.1 — complete:** Added an explicit side-effect-free application
  factory, process-only liveness and fail-closed PostgreSQL/active-model
  readiness with deterministic typed responses.
- **Step 8.2 — complete:** Added validated request IDs, uniform sanitized error
  envelopes and strict reusable offset-pagination contracts without adding a
  collection endpoint.
- **Step 8.3 — complete:** Added deterministic read-only teams and seasons
  collections/details with canonical UUID and registry checksum provenance.
- **Step 8.4 — complete:** Added read-only fixture projections over current,
  result and canonical historical evidence plus latest complete standings.
- **Step 8.5 — complete:** Added persisted immutable three-way prediction reads
  without active-model loading, prediction generation or scoreline inference.
- **Step 8.6 — complete:** Added persisted simulation reads and a deterministic
  predicted table over stored expected values and position probabilities.
- **Step 8.7 — complete:** Added semantic-model assessment, truthful registry
  state and development-only persisted performance metrics.
- **Step 8.8 — next:** Add OpenAPI and API contract tests.
- **Step 8.9:** Add CORS, security headers and rate controls.

**Steps 8.1–8.2 verification:** Python 3.14.7 completed 543 tests with 90.37%
branch-aware coverage. Ruff lint/format, strict mypy over 190 Python files and
dependency consistency passed. Both isolated PostgreSQL targets remain at
`f0009_step_7_9`, all 11 raw captures passed manifest verification and the
actual registry still resolves to `no_active_model` with byte-identical
registry and model artifacts.

**Steps 8.3–8.7 verification:** Python 3.14.7 completed 552 tests with 90.58%
branch coverage. Ruff lint/format over 235 Python files, strict mypy over 196
source/test/migration files and dependency consistency passed. Read-only API
integration checks used only the isolated test database,
preserved relevant row counts and artifact bytes and generated no prediction,
simulation or metric. Both PostgreSQL targets remain at `f0009_step_7_9`; the
actual registry remains `development_accepted` and resolves to
`no_active_model`.

## Milestone J — Live Data, Automation and Retraining — planned

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

- **Step 10.1:** Harden tests, migrations and dependency scanning.
- **Step 10.2:** Create production container/runtime configuration.
- **Step 10.3:** Provision and migrate a hosted PostgreSQL database.
- **Step 10.4:** Deploy FastAPI after current platform research and explicit
  deployment approval.
- **Step 10.5:** Run historical-to-API end-to-end validation.
- **Step 10.6:** Verify secret handling, quotas, recovery and reproducibility.
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
- **Step 11.10:** Add accessibility, component and end-to-end tests.
- **Step 11.11:** Deploy the frontend.
- **Step 11.12:** Run full production integration tests.

## Milestone completion rule

A milestone is complete only when its implementation and documentation agree,
the complete local quality suite passes, generated artifacts are reproducible,
important constraints are recorded and a local milestone commit is created.
