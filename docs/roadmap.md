# Implementation Roadmap

This roadmap is the durable implementation sequence for the Premier League
prediction platform. Each milestone should be completed in its own Codex task,
and each numbered step should remain small enough to review and test in
isolation.

## Milestone A — Repository Foundation — complete

- **Step 0.1:** Establish repository conventions, ignore rules, README, and
  architecture documentation.
- **Step 0.2:** Standardize the local runtime on 64-bit Python 3.14.7 and create
  the project virtual environment.
- **Step 0.3:** Make the package installable and configure local linting,
  formatting, strict typing, testing, and coverage.
- **Step 0.4:** Add typed environment configuration and structured JSON logging
  with secret redaction.
- **Step 0.5:** Add foundation tests and local developer instructions. Remove
  the initially proposed GitHub Actions workflow; CI/CD is intentionally absent.

## Milestone B — Historical Data System — complete

- **Step 1.1:** Define tracked Football-Data source provenance and manifest
  metadata.
- **Step 1.2:** Implement a checksum-verified, immutable downloader.
- **Step 1.3:** Capture and verify the first completed Premier League season.
- **Step 1.4:** Implement a typed Football-Data CSV parser.
- **Step 1.5:** Define the provider-independent canonical fixture schema.
- **Step 1.6:** Implement stable canonical team identity and explicit aliases.
- **Step 1.7:** Implement deterministic canonical dataset materialization.
- **Step 1.8:** Add competition-wide fixture quality validation.
- **Step 1.9:** Add season membership and promotion-transition contracts.
- **Step 1.10:** Expand the reproducible window to 2015–16 through 2025–26 and
  add all-season download and materialization commands.

## Milestone C — Point-in-Time Feature System — complete

- **Step 2.1 — complete:** Define the versioned, provider-independent
  point-in-time feature-row contract, including fixture identity, team identity,
  feature cutoff, kickoff precision, predictor/label separation, and provenance.
  Add contract validation, unit tests, and schema documentation. Do not compute
  rolling features yet.
- **Step 2.2 — complete:** Define chronological processing and same-date batch
  semantics for date-only historical fixtures.
- **Step 2.3 — complete:** Implement leakage-safe rolling team form and result
  features.
- **Step 2.4 — complete:** Implement goals, shots, and discipline rolling
  features using prior matches only.
- **Step 2.5 — complete:** Add rest, schedule congestion, venue, promoted-team,
  and season context features.
- **Step 2.6 — complete:** Materialize deterministic feature datasets with
  source and schema lineage.
- **Step 2.7 — complete:** Add explicit leakage, determinism, missing-data, and
  temporal boundary tests.
- **Step 2.8 — complete:** Produce the first reproducible training dataset from
  every verified feature season, with a versioned row contract, structurally
  separate target, deterministic bytes, and complete checksum provenance.

## Later milestones — planned

1. **Milestone D — Elo Engine — next:** Point-in-time ratings, home advantage, season
   transitions, and reproducible rating history.
2. **Milestone E — Baseline Model and Temporal Validation:** Multinomial logistic
   regression, chronological splits, probabilistic metrics, and baselines.
3. **Milestone F — Main Model and Calibration:** CatBoost or XGBoost evaluation,
   tuning, probability calibration, and reliability analysis.
4. **Milestone G — Score Model and Model Selection:** Dixon–Coles/Poisson score
   modelling, model comparison, and artifact versioning.
5. **Milestone H — Season Simulation:** Monte Carlo table simulation and
   uncertainty outputs.
6. **Milestone I — Persistence and Current Data:** PostgreSQL schema,
   repositories, migrations, and a current-season provider adapter.
7. **Milestone J — Prediction Service:** Prediction lifecycle, FastAPI contracts,
   evaluation, and refresh workflows.
8. **Milestone K — Operational Validation:** Local end-to-end validation and a
   deployment approach chosen only with explicit approval. CI/CD remains out of
   scope unless the user reverses that decision.
9. **Milestone L — Frontend:** Frontend architecture and implementation after the
   backend and models are accepted.

## Milestone completion rule

A milestone is complete only when its implementation and documentation agree,
the complete local quality suite passes, generated artifacts are reproducible,
important constraints are recorded, and a local milestone commit is created.
