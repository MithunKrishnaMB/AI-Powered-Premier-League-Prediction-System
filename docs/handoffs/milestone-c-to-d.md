# Milestone Handoff — C to D

## Handoff purpose

Milestone C — Point-in-Time Features and Elo is complete under the reconciled
master roadmap. This document records the stable boundary for Milestone D —
Probabilistic Models.

## Completed work

- Steps 2.1 through 2.8 are complete.
- Feature rows are immutable, provider-independent and separate predictors,
  post-match labels and checksum-pinned provenance.
- Predictor schema `epl-pre-match` version 2 contains 175 ordered predictors.
- Exact kickoffs are chronological. Any Premier League local date containing a
  date-only fixture is one simultaneous batch, with state updates delayed until
  the complete batch finishes.
- Continuing clubs receive season-opening priors from their immediately
  preceding Premier League season. Promoted clubs receive that season's league
  aggregate and the first tracked season receives a fixed neutral baseline.
- Opening priors have a five-match smoothing weight and explicit source flags;
  they never alter factual current-season observation counts.
- Elo uses a 1500 initial rating, 65-point home advantage, K-factor 20,
  400-point scale and 75% offseason retention for continuing clubs. Promoted
  clubs initialize at 1500.
- Elo predictions use pre-batch ratings. Result deltas from every simultaneous
  fixture are accumulated against that shared snapshot and applied afterward.
- Every later-season feature manifest carries a recursive history checksum and
  its immediate previous canonical source. Rebuilding a target season verifies
  every required raw and canonical predecessor.
- The regenerated Step 2.8 dataset contains all 4,180 historical fixtures with
  structurally separate result/score targets and complete checksum provenance.

## Commands

```powershell
plp-materialize-features `
  --manifest data/manifests/football-data.json `
  --all `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data

plp-materialize-training `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data

ruff check .
ruff format --check .
mypy src tests
pytest --cov
python -m pip check
```

## Acceptance snapshot

- Runtime: 64-bit Python 3.14.7.
- Test suite: 173 passed.
- Branch-aware coverage: 92.01% against the required 90% minimum.
- Ruff lint and format checks: passed.
- Strict mypy: passed for 57 source and test files.
- Dependency consistency and Git whitespace checks: passed.
- Raw verification, canonical materialization, feature materialization and
  training materialization were rerun without changing deterministic outputs.
- Training dataset: 4,180 rows across 11 seasons, 175 predictors, SHA-256
  `d002097c5ccd471eb0987ffc505b544bfcad41e7c73b483f2110badc79054844`.

## Non-negotiable boundaries

- Raw manifest verification and immutable canonicalization remain mandatory.
- Never fuzzy-match team identities or admit retained bookmaker columns as
  predictors without an explicit reviewed schema change.
- Current fixture results, statistics and rating deltas cannot affect their
  own predictors.
- Date-only state updates occur after the entire local-date batch.
- Preserve deterministic IDs, ordering, bytes, checksums and provenance.
- Use chronological validation; do not randomly split the combined training
  dataset.
- Keep Python 3.14.7, strict typing, 90% coverage and local-only quality gates.
- Do not add CI/CD, deployment, databases, APIs or frontend work during
  Milestone D model development.

## Next step

Step 3.1 implements naive and Elo benchmarks. It should define chronological
evaluation windows and probabilistic metrics before fitting more complex models,
and it must treat the Elo expected-score signal as a benchmark without
misrepresenting it as an already calibrated three-way match probability.
