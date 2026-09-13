# Milestone E to F Handoff

## Closed milestone

Milestone E — Registry and Simulation is complete through Step 4.9. The
implementation defines deterministic model artifacts and an append-only
development registry, then builds model-agnostic season simulation around
explicit scoreline distributions.

No final-test prediction or metric was produced and no model was activated.
The 2025–26 target remains sealed.

## Completed implementation

- Steps 4.1–4.3 define and serialize the CatBoost artifact, validate canonical
  component bytes and checksums and record append-only candidate and
  development-accepted registry events with no mutable active pointer.
- Steps 4.4–4.6 define strict simulation inputs, stateless scoreline sampling and
  immutable official table computation.
- Steps 4.7–4.9 execute exactly 10,000 vectorized runs, aggregate complete
  finishing-position and threshold probabilities and enforce deterministic and
  conservation invariants.
- Primary implementation is under `src/pl_platform/registry/`,
  `src/pl_platform/domain/simulation.py` and `src/pl_platform/simulation/`.
- Focused tests are under `tests/unit/registry/` and `tests/unit/simulation/`.

## Stable boundaries

- The selected artifact remains CatBoost depth 6 with identity calibration and
  the fixed `home_win`, `draw`, `away_win` outcome order.
- The artifact has no score model. Simulation accepts only separately supplied,
  content-identified fixture scoreline distributions.
- Simulation schema version 1 uses canonical team and fixture UUIDs, strict UTC
  kickoffs and the established date-only simultaneous-batch policy.
- A scoreline draw is SHA-256-derived from the unsigned 64-bit seed, simulation
  index and fixture UUID and is independent of fixture iteration order.
- Table state is rebuilt from an immutable fixture ledger. Final ranking uses
  points, goal difference, goals scored, head-to-head points and head-to-head
  away goals.
- A unique single-table position fails closed if an official playoff is still
  required. Multi-run aggregation assigns equal fractional mass across the
  unresolved occupied positions without claiming a playoff winner.
- Simulation algorithm version 1 always executes 10,000 runs and exposes
  read-only NumPy matrices.
- Aggregate summaries contain every position probability plus champion,
  top-four, top-six and relegation thresholds with complete league-wide mass.

## Verification at closeout

- Python: 64-bit CPython 3.14.7.
- pytest: 343 passed.
- Branch-aware coverage: 90.86%, above the required 90%.
- Ruff lint and format checks: passed.
- Strict mypy: passed.
- Dependency consistency: passed.
- Repeated 10,000-run inputs and seeds produced identical UUIDs and exact matrix
  values.
- Team and position probability mass and all four league threshold totals were
  complete.
- A complete 380-fixture double round robin conserved per-team and league-wide
  points and goal totals across all 10,000 runs.

## Constraints carried into Milestone F

- Keep the one-time 2025–26 final-test target sealed until separately
  authorized.
- Preserve raw-manifest verification, historical provenance, predictor/target
  separation and point-in-time chronology.
- Never fuzzy-match team identities or promote retained odds columns to
  predictors.
- Do not treat the development-accepted registry entry as active.
- Do not infer score distributions from three-way CatBoost probabilities.
- Preserve deterministic identities, canonical ordering, numerical dtypes and
  checksum semantics when defining persistence.
- Keep artifact components, artifact manifests, registry events, classifier
  metadata, calibration metadata, preprocessing metadata and score-model
  metadata distinct in the persistence design.
- Preserve the fixed `home_win`, `draw`, `away_win` outcome order and Python
  3.14.7 runtime/compatibility pins.
- Do not add APIs, deployment, frontend or CI/CD work before its numbered step.

## Exact next step — 5.1

Finalize the entity-relationship model against the produced canonical fixtures,
features, training/evaluation lineage, model artifacts, registry events,
simulation inputs and aggregate summaries. This is a schema-design boundary;
identify entities, ownership, keys, relationships, uniqueness, immutability and
provenance constraints without configuring or connecting to PostgreSQL.
Database connection configuration begins in Step 5.2, Alembic initialization in
Step 5.3 and migrations in Step 5.4.

## Successor record

Step 5.1 is now complete. Its finalized design and the Step 5.2 boundary are
recorded in the [Step 5.1 to 5.2 handoff](step-5-1-to-5-2.md). This document
remains the historical Milestone E closeout record.
