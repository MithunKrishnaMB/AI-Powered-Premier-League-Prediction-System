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

## Milestone I — FastAPI — complete

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
- **Step 8.8 — complete:** Published the reviewed OpenAPI 3.1 document and
  Swagger UI with stable operation IDs, shared error schemas and contract tests
  proving the exact GET-only path surface.
- **Step 8.9 — complete:** Added exact-origin CORS, deterministic security
  headers and bounded direct-peer sliding-window rate controls inside the
  request-ID/error boundary.

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

**Steps 8.8–8.9 verification:** Python 3.14.7 completed 565 tests with 90.69%
branch coverage. Ruff lint/format over 240 Python files, strict mypy over 199
source/test/migration files, dependency consistency and diff checks passed.
OpenAPI contract tests pin all 16 GET operations and prohibit mutation verbs;
transport tests cover CORS, security headers and bounded rate behavior. No
provider, target, registry, artifact or database mutation occurred.

**Milestone I closeout:** Commit `c74ba9b` records the completed implementation,
architecture and handoff documentation for Steps 8.1 through 8.9. The API
remains GET-only and import-safe; liveness is dependency-independent, readiness
fails closed, database reads are environment-isolated and read-only, the actual
registry remains `development_accepted` with no active model and the sealed
2025–26 target remains untouched. No provider, production artifact corpus,
deployment, frontend, scheduled automation or CI/CD configuration was added.
Its handoff boundary was Step 9.1, cache-aware live fixture reads under the
existing provider-neutral and exact-cache boundaries.

## Milestone J — Live Data, Automation and Retraining — complete

- **Step 9.1 — complete:** Added provider-neutral read-through fixture pages
  over the immutable exact-response cache. Fresh compatible bytes avoid
  provider contact; stale and missing entries refresh only through an explicitly
  supported capability; incompatible entries fail closed. Complete pagination,
  canonical fixture identity and per-page retrieval/expiry provenance are
  retained without selecting a provider, synchronizing fixture tables or
  changing FastAPI.
- **Step 9.2 — complete:** Added a pure deterministic kickoff-aware polling
  policy and a composable fixture read/synchronize/plan job. Exact and date-only
  kickoffs, live, postponed and terminal states have explicit polling bands;
  the policy schedules nothing itself.
- **Step 9.3 — complete:** Added exact-cache-aware completed-result retrieval.
  Complete pagination and canonical identity validation precede one immutable,
  raw-manifest-gated reconciliation write; empty complete responses are no-ops.
- **Step 9.4 — complete:** Added `plp-current-data` fixture-poll and final-match
  commands with mandatory UTC time, season and development/test target. The
  default runtime fails closed because no provider has been selected.
- **Step 9.5 — complete:** Added an explicit in-memory candidate retraining
  workflow. It pairs immutable pre-match feature rows with official results,
  excludes the sealed season, refits the fixed CatBoost depth-6 policy and
  emits a deterministic `candidate_unassessed` manifest without serializing an
  artifact or mutating the registry.
- **Step 9.6 — complete:** Added an explicit canonical comparison report over
  a strictly later, disjoint operational holdout. Identical-population proper
  scores drive deterministic insufficient/retain/review decisions; every
  report requires human review and fixes registry disposition to no change.
- **Step 9.7 — complete:** Added a passive deterministic operational snapshot
  plus a manual observability and failure-response runbook. The snapshot fixes
  the supported truth to `development_accepted`, zero active models and
  explicit manual execution only.

The former scheduled GitHub Actions item was removed from this roadmap by
explicit user direction. It was not implemented and the remaining items were
renumbered. No substitute scheduler, automation, CI/CD or DevOps configuration
is part of Milestone J.

**Step 9.1 verification:** Python 3.14.7 completed 579 tests with 90.82%
branch coverage. Ruff lint/format passed over 244 Python files, strict mypy
passed over 202 source/test/migration files and dependency consistency passed.
PostgreSQL integration verified exact fresh, stale and missing cache states only
against the isolated test target. The OpenAPI contract remains the same sixteen
GET operations. No provider, normalized fixture synchronization, prediction,
simulation, registry transition, artifact import, sealed-target access,
scheduler, deployment, frontend or CI/CD configuration was added.

**Steps 9.2–9.4 verification:** Python 3.14.7 completed 617 tests with 91.08%
branch coverage. Ruff lint/format checked 255 Python files, strict mypy checked
212 source/test/migration files and dependency consistency passed. Unit,
exact-byte contract and live PostgreSQL integration checks cover polling bands,
date-only semantics, lazy imports, safe command parsing, cache hit/stale/miss
behavior, capability failures, pagination, idempotence and
prior-fixture-backed result persistence.

**Step 9.5 verification:** Python 3.14.7 completed 630 tests with 91.04% branch
coverage. Ruff lint/format checked 260 Python files, strict mypy checked 216
source/test/migration files and dependency consistency passed. Focused unit and
canonical-contract checks cover baseline verification, exact operational
feature/result pairing, sealed-target and chronology rejection, deterministic
candidate identity and the explicit absence of artifact, metric, promotion and
registry behavior.

**Steps 9.6–9.7 verification:** Python 3.14.7 completed 642 tests with 91.06%
branch coverage. Ruff lint/format checked 266 Python files, strict mypy checked
220 source/test/migration files and dependency consistency passed. Focused unit
and canonical-contract tests cover later/disjoint evidence, sealed-target and
chronology rejection, exact baseline/candidate populations, all three report
decisions, checksum drift, passive signal mapping and zero registry mutation.
All 11 historical captures remained exact-manifest verified and the live
PostgreSQL suite remained isolated to the explicit test target.

**Milestone J closeout:** Steps 9.1 through 9.7 are complete. The scheduled
automation item was explicitly removed and no substitute scheduler, CI/CD,
GitHub Actions, deployment or DevOps configuration exists. Commit `059c226`
records the completed comparison and passive-observability implementation on
top of the earlier live-data and retraining work. The final Python 3.14.7 suite
passes 642 tests with 91.06% branch coverage; Ruff lint/format, strict mypy over
220 source/test/migration files, dependency consistency, PostgreSQL isolation,
historical manifest verification, diff whitespace and local Markdown-link
checks pass. The actual registry remains `development_accepted` with no active
model, no final-test evidence was created and the sealed 2025–26 targets remain
uninspected.

**Milestone J closeout boundary (historical):** Milestone K Step 10.1 was the
next local-only hardening audit of tests, migration verification and dependency
checks. It required separate approval and did not add CI/CD, GitHub Actions,
scheduling, deployment, containers, hosted infrastructure or another DevOps
substitute.

## Milestone K — Backend Release — complete

- **Step 10.1 — complete:** Hardened the explicit local release test mode,
  dependency-pin and environment integrity checks, package-wide import safety,
  exact Alembic graph verification and a rollback-only full migration cycle on
  the isolated test database. No automation or external infrastructure was
  added.
- **Step 10.2 — complete:** Added a digest-pinned Python 3.14.7 image, explicit
  production-only Uvicorn entry point, non-root single-worker process,
  deny-by-default build context, liveness healthcheck and deterministic local
  process/image verification. The empty image remains fail-closed and not
  ready; it contains no secrets, database configuration or artifact corpus.
- **Step 10.3 — complete:** Created the Neon Free PostgreSQL 18 project in
  Singapore, migrated the schema-only database through `f0009_step_7_9` and
  verified the dedicated pooled `pl_api` role. It can select all 111 migrated
  tables, has no table write privilege and has no elevated PostgreSQL role
  capability. The direct owner URL was never transmitted to Render.
- **Step 10.4 — complete:** Deployed the exact reviewed commit as one manually
  released Render Free Docker service in Singapore. Auto-deploy remains off,
  `/health/live` is the platform health check and the runtime has only the
  pooled read-only database credential. Public acceptance preserved the
  sixteen-operation GET-only API, request IDs, error envelopes, pagination,
  OpenAPI, CORS, security headers and rate limiting. Readiness intentionally
  remains HTTP 503 because PostgreSQL is ready but no active model exists.
- **Step 10.5 — complete:** Added rollback-only historical-to-API validation
  over the real 2024–25 raw/canonical lineage, 20 season members and all 380
  fixtures. It exercises the PostgreSQL projections and FastAPI transport,
  repeats byte-identical reads and persists no database or artifact change.
  Revision `f0010_step_10_5` repairs the canonical validator's obsolete
  `is_complete` reference without changing data, tables or privileges.
- **Step 10.6 — complete:** Pinned the exact seven-variable Render boundary,
  secret exclusions and bounded free-tier pool; verified HTTP/provider quotas,
  transient database recovery, existing workflow recovery and deterministic
  replay; and documented manual credential and deployment recovery.
- **Step 10.7 — complete:** Published commit `569504f`, applied
  `f0010_step_10_5` to Neon with the direct owner credential, reverified the
  unprivileged read-only `pl_api` surface, manually deployed that exact commit
  to Render and repeated the public backend contract acceptance. The gate
  passed without importing a corpus or creating an active model.

**Steps 10.1 and 10.2 boundary:** The release-only pytest mode requires both
restricted, isolated local PostgreSQL targets at exact head, all eleven
historical raw captures and the actual single `development_accepted` registry
history with no active model. It rejects skipped local evidence, validates all
nine migration upgrades after a complete downgrade inside a rollback-only
test-database transaction and enforces exact direct dependency pins, local
dependency consistency, Python 3.14.7 and side-effect-free package imports. The
production image adds only the pinned Uvicorn server and packages that verified
backend as one non-root, production-only process without copying local evidence.

**Step 10.1 verification:** Python 3.14.7 completed 648 tests with no skips and
91.06% branch coverage. Ruff lint and formatting passed over 273 files, strict
mypy passed over 225 source/test/migration files and dependency consistency
passed. The release gate verified both restricted PostgreSQL 18.4 targets at
`f0009_step_7_9`, completed the rollback-only nine-revision test-database cycle,
verified all eleven raw captures and required the actual registry to remain
`development_accepted` with zero active models.

**Step 10.2 verification:** The digest-pinned image builds locally, runs as
UID/GID 10001 under one Uvicorn worker and becomes container-healthy through
HTTP 200 liveness. Its empty production state returns HTTP 503 readiness with
`production_database_not_configured` and `no_active_model`; request IDs,
production HSTS and the sixteen GET-only OpenAPI paths remain intact. A
non-production environment override exits before Uvicorn starts. The complete
Python 3.14.7 release suite passes 653 tests with no skips and 91.07% branch
coverage; Ruff passes across 279 files, strict mypy passes across 229 Python
files and dependency consistency passes.

**Steps 10.3 and 10.4 verification:** Python 3.14.7 completes 666 tests
with no skips and 91.10% branch coverage. Ruff lint and formatting pass across
281 files, strict mypy passes across 230 source/test/migration files and
dependency consistency passes. Tests require explicit TLS production URLs,
separate migration authority, configured-production database selection,
Render's dynamic port, manual free Singapore Blueprint, liveness health check,
secret prompting and validated trusted-edge rate-limit identity. Hosted Neon
verification additionally confirms PostgreSQL 18.6 in UTC, exact migration
head `f0009_step_7_9`, 111 of 111 tables selectable by `pl_api`, zero tables
with write privilege and every elevated role flag disabled. The public Render
service returns HTTP 200 liveness, reports PostgreSQL `ready` plus
`no_active_model` in its intentional HTTP 503 readiness response, exposes
exactly sixteen GET operations and rejects an untrusted CORS origin. The final
manual deployment of commit `461f31f` completed successfully.

**Steps 10.5 and 10.6 verification:** Python 3.14.7 completes 669 tests with no
skips and 91.12% branch coverage. Ruff lint and formatting pass across 287
files, strict mypy passes across 232 source/test/migration files and dependency
consistency passes. The ten-revision migration cycle reaches
`f0010_step_10_5`; local development and test databases are at that exact head.
The rollback-only historical acceptance proves 20 members, 380 finished
fixtures, exact pagination and filters, empty prediction and simulation
collections, byte-identical replay and no persistent database or artifact
change. Static deployment checks preserve the exact seven-variable Render
boundary and transient database failure produces a sanitized 503 before a
fresh engine succeeds on the next request.

**Step 10.7 verification:** Commit
`569504f2775c2e6092a956248266a9052e584a66` is published on `main`. Neon
PostgreSQL 18.6 is at exact head `f0010_step_10_5`; all 111 application
relations remain selectable by `pl_api`, none is writable and every elevated
role capability remains disabled. Render deployment
`dep-dapl3f3bc2fs73b49lu0` built that exact commit and reached Live in 2m30s.
Public acceptance returned HTTP 200 liveness and the intentional HTTP 503
readiness with PostgreSQL `ready` and `no_active_model`; it preserved exactly
sixteen GET operations, empty pagination, request-ID echo, uniform 404/422
envelopes, HSTS and other security headers, the 120-request rate-limit contract
and HTTP 403 denial of an untrusted CORS origin.

**Milestone K closeout:** Commit `1669b6a` records the completed release and
handoff documentation for Steps 10.1 through 10.7. The complete Python 3.14.7
release suite for the deployed commit passes 669 tests with no
skips and 91.12% branch coverage; Ruff, strict mypy and dependency consistency
pass. The production database and service now match the reviewed release while
remaining deliberately empty and fail-closed without an active model. No
automation, CI/CD, paid resource, provider, production artifact corpus,
prediction, simulation, registry mutation or sealed-target access was added.

**Milestone L architecture boundary:** Step 11.1 confirms one isolated Next.js
16 App Router package below `frontend/`, Node.js 24.21.0 LTS with npm 11.19.0,
strict TypeScript, deterministic local OpenAPI generation, server-owned no-store
reads, URL-owned navigation state, explicit empty/unavailable/cold-start
experiences, WCAG 2.2 AA and one later manually deployed zero-cost frontend
service. No frontend code, package, dependency, client or infrastructure was
created.

**Exact next action:** Milestone L Step 11.2 is the frontend foundation. It has
not started. Initialize only the Next.js/TypeScript package and deterministic
generated API-client boundary; do not begin the dashboard or another feature.

## Milestone L — Frontend, Last — in progress

- **Step 11.1 — complete:** Reassessed the framework, strict TypeScript and npm
  boundary, deterministic locally exported OpenAPI client, Server/Client
  Component ownership, routing, no-store data access, URL state, pagination,
  request IDs, error mapping, user experience states, accessibility, responsive
  styling, testing, browser support, environment/CORS assumptions, manual
  zero-cost deployment and the ordered feature map. Documentation only; no
  frontend was initialized.
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

**Step 11.1 page and contract boundary:** Later pages are ordered as dashboard;
fixtures and predictions; teams with truthful squad unavailability; actual and
predicted standings; simulations; history and development-only model evidence;
and a manually refreshed persisted-state match centre. The current API has no
player/squad operation or live-provider route, so later frontend work must not
invent either capability or expand the fixed sixteen-operation GET-only
contract implicitly. See the
[frontend application architecture](architecture/frontend-application.md) and
[Step 11.1 to 11.2 handoff](handoffs/step-11-1-to-11-2.md).

**Step 11.1 verification:** Python 3.14.7 Ruff lint and formatting pass across
290 files, strict mypy passes across 232 source/test/migration files and
dependency consistency passes. Twenty-two focused application, OpenAPI,
request-ID/error, pagination and HTTP-control tests pass. Documentation links
and diff whitespace pass. No frontend, dependency, generated artifact,
automation or infrastructure file exists.

## Milestone completion rule

A milestone is complete only when its implementation and documentation agree,
the complete local quality suite passes, generated artifacts are reproducible,
important constraints are recorded and a local milestone commit is created.
