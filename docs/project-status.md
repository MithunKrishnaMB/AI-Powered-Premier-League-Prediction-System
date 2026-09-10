# Project Status

**Status date:** 2026-09-10  
**Runtime:** 64-bit Python 3.14.7  
**Completed milestones:** A — Repository Foundation; B — Historical Data System  
**Current milestone:** B closed  
**Next milestone:** C — Point-in-Time Feature System  
**Exact next step:** Step 2.1 — define the point-in-time feature-row contract

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

## Historical dataset status

- Seasons: 2015–16 through 2025–26 inclusive.
- Completed-season source files: 11.
- Fixtures per season: 380.
- Total canonical fixtures: 4,180.
- Exact source kickoff timestamps: 2,660.
- Date-only source kickoffs: 1,520 across 2015–16 through 2018–19.
- Canonical dataset schema version: 2.
- Raw data location: `data/raw/football-data/epl/<season>/E0.csv`.
- Canonical location:
  `data/interim/canonical/epl/<season>/fixtures.jsonl`.
- Raw and interim files are reproducible local artifacts and are ignored by Git.

## Last verified quality result

The Milestones A and B closeout passed the complete local suite:

- pytest: 84 passed.
- branch-aware coverage: 93.30% (minimum required: 90%).
- Ruff lint: passed.
- Ruff format check: passed.
- strict mypy: passed.
- package dependency check: passed.
- deterministic materialization rerun: all 11 seasons returned
  `already_current`.

The milestone-closeout commit should rerun these commands before it is created;
the handoff records the final closeout result.

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
  future point-in-time feature updates.
- Retained bookmaker columns are not automatically eligible model features.
- Preserve a strict separation between predictors, labels, and provenance to
  prevent target leakage.
- Develop the backend and ML system before the frontend.

## Not implemented yet

- Point-in-time feature rows or feature computation.
- Elo ratings.
- Model training, calibration, or score modelling.
- Temporal cross-validation.
- Season simulation.
- PostgreSQL persistence or migrations.
- Current-season provider integration.
- FastAPI endpoints.
- Deployment or frontend code.

## Exact next step acceptance boundary

Step 2.1 defines and tests the feature-row contract only. It should establish a
versioned schema that identifies the fixture, teams, season, feature cutoff,
kickoff precision, predictors, training label, and source lineage. It must reject
internally inconsistent or temporally invalid records and document which fields
are predictors versus labels. Rolling calculations, Elo, model training, database
work, APIs, deployment, and frontend work are outside Step 2.1.
