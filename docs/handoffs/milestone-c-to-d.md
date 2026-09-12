# Milestone Handoff — C to D

## Handoff purpose

Milestone C — Point-in-Time Feature System is complete. This document records
the stable boundary required to begin Milestone D — Elo Engine without changing
or weakening the accepted feature semantics.

## Completed work

- Steps 2.1 through 2.8 are complete.
- Feature rows are immutable, versioned, provider-independent, and separate
  predictors, post-match labels, and checksum-pinned provenance.
- Exact kickoffs are processed chronologically; a Premier League local date
  containing any date-only record is one pre-date simultaneous batch.
- Team state updates only after all rows in a batch are built.
- Predictor schema `epl-pre-match` version 1 contains 134 ordered predictors for
  results, five-match form, goals, shots, fouls, cards, rest, congestion, venue,
  promotion, and season progress.
- Missing optional statistics remain null and carry observed denominators.
- All 4,180 historical rows materialize beneath ignored
  `data/processed/features/` with deterministic checksums and complete raw and
  canonical lineage.
- A second all-season build returned `already_current` for all 11 datasets.
- The first combined model-ready dataset contains all 4,180 fixtures with the
  same 134 predictors and a structurally separate result/score target.
- Training rows and the adjacent manifest are deterministic and checksum-pin
  every feature dataset and manifest, canonical dataset, raw artifact, and
  tracked registry/manifest input.

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

## Non-negotiable boundaries

- Raw manifest verification and immutable canonicalization remain mandatory.
- Never fuzzy-match team identities or admit retained bookmaker columns as
  features without an explicit reviewed schema change.
- Do not use the current fixture's result or statistics in its predictors.
- Date-only state updates occur after the entire local-date batch.
- Preserve deterministic IDs, ordering, bytes, checksums, and lineage.
- Keep Python 3.14.7, strict typing, 90% coverage, and local-only quality gates.
- Do not add CI/CD, deployment, databases, APIs, or frontend work during the Elo
  milestone.

## Next milestone

Milestone D should first define a versioned Elo state and rating-row contract,
including initialization, home advantage, K-factor/update policy, season
transitions, chronological batch integration, and reproducible rating lineage.
Only after that contract is reviewed should rating calculations and history
materialization be implemented.
