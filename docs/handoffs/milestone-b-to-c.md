# Milestone Handoff — B to C

## Handoff purpose

Milestones A — Repository Foundation and B — Historical Data System are complete.
This document gives a new Codex task the durable context required to begin
Milestone C without relying on the previous chat transcript.

## Completed work

- Steps 0.1 through 0.5 are complete.
- Steps 1.1 through 1.10 are complete.
- The package, configuration, structured logging and local quality gates are in
  place.
- Eleven checksum-pinned Football-Data EPL seasons are locally reproducible.
- All 4,180 fixtures canonicalize successfully against 34 reviewed club
  identities and 11 season registries.
- Per-row, domain, cross-record, lineage, atomic-write and idempotency behavior
  are covered by tests.
- The second materialization pass returned `already_current` for every season.
- CI/CD and the initially created GitHub Actions workflow were removed by user
  decision.

## Read first in the next task

1. `README.md`
2. `docs/roadmap.md`
3. `docs/project-status.md`
4. `docs/architecture/decisions.md`
5. `docs/data/schemas.md`
6. `docs/data/historical-data.md`
7. `src/pl_platform/domain/fixtures.py`
8. `src/pl_platform/ingestion/materialize.py`
9. `src/pl_platform/quality/fixtures.py`

## Local environment and commands

Use the existing project directory and Python 3.14 virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --editable .
python -m pip install --group dev
```

Run the complete local quality suite with:

```powershell
ruff check .
ruff format --check .
mypy src tests
pytest --cov
python -m pip check
```

Reproduce or verify all historical data with:

```powershell
plp-download-historical --manifest data/manifests/football-data.json --all --data-root data
plp-materialize-historical --manifest data/manifests/football-data.json --all --teams data/reference/teams.json --seasons data/reference/seasons.json --data-root data
```

Raw and interim data are ignored by Git. A new task should use the same local
checkout if it needs the already downloaded files. A separate Git worktree will
not automatically contain those ignored datasets or `.venv`.

## Non-negotiable constraints

- Do not add GitHub Actions, YAML CI/CD or deployment automation.
- Ask for explicit approval before every project-changing numbered step.
- Use Python 3.14.7 and keep strict typing and the 90% coverage gate.
- Do not silently overwrite raw data or bypass manifest verification.
- Do not fuzzy-match team identities.
- Do not treat retained odds columns as approved model features.
- Prevent temporal and target leakage by construction.
- For `date_only` fixtures, calculate all same-date features from pre-date state
  and apply match updates only after the whole date batch.
- Preserve deterministic IDs, outputs, checksums and provenance.

## Exact next step

**Step 2.1 — Define the point-in-time feature-row contract.**

The step should add a versioned provider-independent schema for one fixture's
pre-match feature row. It must explicitly represent fixture, season and team
identity; kickoff and its precision; feature cutoff; predictor values; training
label; and source/schema provenance. Predictors and post-match labels must be
structurally distinguishable. Validation must reject inconsistent teams,
non-UTC timestamps and a feature cutoff later than the fixture's information
boundary. Add unit tests and update schema documentation.

Do not implement rolling feature calculations, Elo, models, persistence, APIs,
deployment or frontend code in Step 2.1.

## Step 2.1 completion evidence expected

- New feature contract is typed, immutable and versioned.
- Temporal and domain invariants have focused unit tests.
- Predictor, label and provenance semantics are documented.
- Existing historical tests continue to pass.
- The complete local quality suite remains green.
- The user receives a concise summary and approves Step 2.2 separately.
