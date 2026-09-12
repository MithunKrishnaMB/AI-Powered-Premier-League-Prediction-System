# AI-Powered Premier League Prediction Platform

A backend-first data, machine-learning, simulation and analytics platform for
probabilistic Premier League forecasting.

The system will ingest historical and current-season football data, construct
strictly point-in-time features, estimate match-result and scoreline
probabilities and simulate the remainder of a season. It will eventually expose
those results through a FastAPI service and a separately developed web frontend.

## Priorities

1. Correctness and prevention of data leakage
2. Reproducible data and model pipelines
3. Well-calibrated probabilistic forecasts
4. Reliable ingestion and persistence
5. Automated testing and maintainability
6. Zero-cost or free-tier-friendly deployment
7. Frontend presentation after the backend is validated

## Planned system

```text
historical sources -> normalization -> point-in-time features -> model training
current provider   -> database/cache -> predictions -> season simulation -> API
completed matches  -> evaluation -> Elo/state updates -> refreshed forecasts
```

The initial backend and ML milestone does not require live scores, player-level
data, Redis, WebSockets or a frontend. Those capabilities will be introduced
only after the historical pipeline, models, simulation, persistence and API are
working together and tested.

## Repository status

The project has an importable Python package, typed configuration, structured
logging, local quality tooling, a checksum-pinned historical ingestion pipeline,
and a versioned point-in-time feature system. Eleven completed Premier League
seasons (2015–16 through 2025–26) can be downloaded, canonicalized, validated,
and transformed into leakage-safe rolling predictors. Per-season feature
datasets and the combined 4,180-row training dataset are reproducibly
materialized with checksum-pinned lineage. Versioned season-opening priors and a
point-in-time Elo engine are included in predictor schema version 2. Deterministic
naive and Elo benchmarks, multinomial logistic regression and five-fold
expanding-season validation now cover the 2015–16 through 2024–25 development
window; 2025–26 remains outside model fitting and evaluation. Model registries,
database migrations and the frontend have not been created. CI/CD automation is
intentionally not configured.

The development environment uses 64-bit Python 3.14.

## Local setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --editable .
python -m pip install --group dev
```

Copy `.env.example` to `.env` only when local overrides are needed. `.env` is
ignored and must not be committed.

Run the quality checks with:

```powershell
ruff check .
ruff format --check .
mypy src tests
pytest --cov
```

## Historical data acquisition

Historical source metadata is versioned in `data/manifests/`. Raw third-party
files are checksum-verified, stored below the ignored `data/raw/` directory and
never overwritten by the downloader.

Download or verify the complete historical window with:

```powershell
plp-download-historical `
  --manifest data/manifests/football-data.json `
  --all `
  --data-root data
```

Materialize all validated canonical fixture datasets with:

```powershell
plp-materialize-historical `
  --manifest data/manifests/football-data.json `
  --all `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

The 4,180 generated fixture records and their per-season build manifests are
written beneath `data/interim/` and remain outside Git. Pass `--entry-id`
instead of `--all` to process one season.

Materialize deterministic point-in-time feature datasets with:

```powershell
plp-materialize-features `
  --manifest data/manifests/football-data.json `
  --all `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

This command re-verifies raw inputs and canonical materialization before writing
4,180 feature rows with 175 predictors and companion lineage manifests beneath
`data/processed/features/`. A second unchanged run returns `already_current`.

Produce the first reproducible training dataset with:

```powershell
plp-materialize-training `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

This command re-verifies every raw, canonical and feature input before writing
the combined model-ready JSON Lines dataset and its lineage manifest beneath
`data/processed/training/`. Predictors and post-match targets remain separate;
the command does not fit a model or define a temporal train/test split.

Evaluate the deterministic benchmarks and multinomial logistic model with:

```powershell
plp-evaluate-models `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

The command re-runs the raw-verifying training materializer before producing
target-free prediction rows and a checksum-pinned evaluation manifest beneath
`data/processed/evaluation/`. It uses fixed chronological holdout and expanding
walk-forward windows and never randomly splits the combined corpus.

See [historical data provenance](docs/data/historical-data.md) for source and
integrity details.

## Data and artifact policy

- Raw third-party data is immutable and is not committed to Git.
- Source URLs, checksums, schema versions and reproducibility metadata belong in
  `data/manifests/` and may be committed.
- Intermediate and processed datasets are generated locally and ignored.
- Trained model binaries are generated artifacts and ignored.
- Secrets belong in local environment configuration and must never be committed.
- Historical predictions and model metadata will ultimately be persisted as
  immutable, versioned records.

## Documentation

Architecture decisions and component documentation will evolve with the
implementation. Start with:

- [implementation roadmap](docs/roadmap.md)
- [current project status](docs/project-status.md)
- [architecture index and decisions](docs/architecture/README.md)
- [Milestone B to C handoff](docs/handoffs/milestone-b-to-c.md)
- [Milestone C to D handoff](docs/handoffs/milestone-c-to-d.md)

## Development order

The planned order is:

1. Repository and Python foundation
2. Historical ingestion and canonical data
3. Point-in-time features and Elo
4. Probabilistic match and score models
5. Season simulation and model versioning
6. PostgreSQL persistence and current-provider integration
7. Prediction lifecycle and FastAPI
8. Automation, deployment and end-to-end backend validation
9. Frontend architecture and implementation

Milestone D is in progress. Steps 3.1 through 3.3 provide naive and Elo
benchmarks, multinomial logistic regression and expanding walk-forward
validation. The next step is **Step 3.4: freeze an untouched test season**;
2025–26 has deliberately not been used by the implemented development
evaluation.
