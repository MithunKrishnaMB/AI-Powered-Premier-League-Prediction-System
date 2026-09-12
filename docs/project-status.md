# Project Status

**Status date:** 2026-09-12
**Runtime:** 64-bit Python 3.14.7
**Completed milestones:** A — Repository Foundation; B — Historical Data System;
C — Point-in-Time Feature System

**Current milestone:** C closed

**Next milestone:** D — Elo Engine

## Implemented capabilities

- Installable `pl_platform` package using the `src/` layout.
- Typed, immutable environment configuration.
- Structured JSON logging with recursive key-based secret redaction.
- Local Ruff, strict mypy, pytest, branch coverage, and dependency checks.
- Versioned Football-Data manifest with HTTPS host allowlisting.
- Immutable, checksum-verified, idempotent historical downloads.
- Typed Football-Data row parsing with retained additional source fields.
- Provider-independent fixture, score, statistics, team, and season contracts.
- Explicit canonical alias resolution for 34 clubs; no fuzzy identity matching.
- Reviewed membership and promotion metadata for 11 seasons.
- Dataset-wide double-round-robin and season-integrity checks.
- Deterministic JSON Lines materialization with companion lineage manifests.
- Batch `--all` and single-entry ingestion commands.
- Immutable, versioned point-in-time feature-row contract.
- Deterministic feature-row identity with canonical and raw-source lineage.
- Structural predictor/training-label separation and temporal boundary checks.
- Deterministic exact-kickoff and conservative whole-date fixture batches.
- Pre-batch snapshots with post-batch result and statistic updates.
- Season-to-date and five-match result, goal, shot, foul, and card features.
- Missing-statistic observation counts without fabricated zero values.
- Rest, congestion, venue, promoted-team, and season-progress context.
- Atomic, deterministic feature JSON Lines with companion lineage manifests.
- Single-season and all-season feature-materialization command.
- Explicit leakage, temporal, missing-data, checksum, and idempotency tests.
- Immutable, versioned training-example contract with separate predictors and
  result/score target.
- Deterministic all-season training-dataset materialization with typed loading
  and complete feature, canonical, raw, manifest, and registry provenance.

## Historical dataset status

- Seasons: 2015–16 through 2025–26 inclusive.
- Completed-season source files: 11.
- Fixtures per season: 380.
- Total canonical fixtures: 4,180.
- Exact source kickoff timestamps: 2,660.
- Date-only source kickoffs: 1,520 across 2015–16 through 2018–19.
- Validated in-memory feature rows: 4,180.
- Materialized feature rows: 4,180.
- Predictor schema: `epl-pre-match` version 1 with 134 ordered predictors.
- Feature dataset schema version: 1.
- Training rows: 4,180, with 380 from each of the 11 seasons.
- Training targets: 1,853 home wins; 1,337 away wins; 990 draws.
- Training row and dataset schema versions: 1.
- Training SHA-256:
  `23f96f0d7152ebabf99a218d9d1a33128723efef1bf164496259b5042cbc0a1b`.
- Canonical dataset schema version: 2.
- Raw data location: `data/raw/football-data/epl/<season>/E0.csv`.
- Canonical location:
  `data/interim/canonical/epl/<season>/fixtures.jsonl`.
- Training location:
  `data/processed/training/epl/2015-2016_to_2025-2026/training.jsonl`.
- Raw, interim, and processed files are reproducible local artifacts and are
  ignored by Git.

## Last verified quality result

The Milestone C implementation passed the complete local suite:

- pytest: 159 passed.
- branch-aware coverage: 92.55% (minimum required: 90%).
- Ruff lint: passed.
- Ruff format check: passed.
- strict mypy: passed.
- package dependency check: passed.
- raw manifest verification returned `already_present` for all 11 seasons.
- canonical materialization returned `already_current` for all 11 seasons.
- all 4,180 canonical fixtures produced feature rows; rebuilding from reversed
  input order produced identical serialized in-memory rows per season.
- first feature materialization wrote all 11 season datasets; the second pass
  returned `already_current` for every season with unchanged SHA-256 checksums.
- two final all-season training builds returned `already_current` with 4,180
  rows and the same SHA-256; typed loading confirmed 380 rows per season and the
  recorded target distribution.

## Important project constraints

- Do not add GitHub Actions, YAML-based CI/CD, or other CI/CD automation unless
  the user explicitly changes this decision.
- Use Python 3.14.7 and preserve the declared `>=3.14,<3.15` support window.
- Keep secrets in ignored local environment files; never commit `.env`.
- Raw provider files are immutable and ignored by Git.
- Never overwrite conflicting raw data. A provider correction requires a
  reviewed manifest change or a separately identified capture.
- Canonical team mappings are explicit. Unknown aliases must fail rather than be
  fuzzy-matched.
- Store canonical timestamps in UTC after interpreting Football-Data timestamps
  in `Europe/London`.
- Treat `date_only` fixtures on the same date as a simultaneous batch during
  point-in-time feature updates.
- Retained bookmaker columns are not automatically eligible model features.
- Preserve a strict separation between predictors, labels, and provenance to
  prevent target leakage.
- Develop the backend and ML system before the frontend.

## Not implemented yet

- Elo ratings.
- Model training, calibration, or score modelling.
- Temporal cross-validation.
- Season simulation.
- PostgreSQL persistence or migrations.
- Current-season provider integration.
- FastAPI endpoints.
- Deployment or frontend code.

## Next milestone boundary

Milestone D adds point-in-time Elo ratings, home advantage, reviewed
initialization and season-transition rules, deterministic rating history, and
tests showing ratings update only after the relevant chronological batch. It
must not retroactively change the completed feature dataset schema without an
explicit schema-version decision.
