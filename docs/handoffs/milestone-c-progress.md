# Milestone C Progress Note

## Purpose

The user-supplied master roadmap places point-in-time features and Elo together
in Milestone C. This note supersedes the premature C-to-D handoff created from a
condensed roadmap. Milestone C remains in progress.

## Completed work

- Steps 2.1 through 2.4 are complete.
- Point-in-time feature rows are immutable, versioned, provider-independent,
  and separate predictors, post-match labels, and checksum-pinned provenance.
- Exact kickoffs are processed chronologically. A Premier League local date
  containing any date-only record is one pre-date simultaneous batch, and team
  state updates only after the full batch.
- Predictor schema `epl-pre-match` version 1 contains 134 ordered prior-only
  predictors covering results, form, goals, shots, discipline, rest,
  congestion, venue, promotion flags, and season progress.
- All 4,180 historical feature rows materialize reproducibly beneath ignored
  `data/processed/features/` with raw and canonical lineage.
- The feature-system portion of Step 2.7 has explicit leakage, temporal,
  missing-data, checksum, reversed-order, and idempotency tests.
- Step 2.8 is complete ahead of the remaining work. The first combined
  model-ready dataset contains 4,180 fixtures with structurally separate
  predictors and result/score targets and full checksum provenance.

## Remaining work

- **Step 2.5 — next:** Define and implement explicit season-opening priors.
  Version 1 currently resets state at each season boundary and deliberately has
  no cross-season carryover.
- **Step 2.6:** Implement Elo initialization, pre-match prediction, post-batch
  update, home advantage, and season transitions.
- **Step 2.7:** Add adversarial invariants covering the approved prior and Elo
  semantics.
- Regenerate and version the Step 2.8 dataset if the approved predictor schema
  changes.

## Non-negotiable boundaries

- Raw manifest verification and immutable canonicalization remain mandatory.
- Never fuzzy-match team identities or treat retained bookmaker columns as
  approved features.
- Current-fixture results and statistics must not enter pre-match predictors.
- Date-only state updates occur after the entire local-date batch.
- Preserve deterministic IDs, ordering, bytes, checksums, and lineage.
- Keep Python 3.14.7, strict typing, 90% coverage, and local-only quality gates.
- Do not add CI/CD, deployment, databases, APIs, or frontend work during these
  steps.
