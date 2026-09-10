# AI-Powered Premier League Prediction Platform

A backend-first data, machine-learning, simulation, and analytics platform for
probabilistic Premier League forecasting.

The system will ingest historical and current-season football data, construct
strictly point-in-time features, estimate match-result and scoreline
probabilities, and simulate the remainder of a season. It will eventually expose
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
data, Redis, WebSockets, or a frontend. Those capabilities will be introduced
only after the historical pipeline, models, simulation, persistence, and API are
working together and tested.

## Repository status

The project has a minimal importable Python package, typed environment
configuration, structured logging, foundational quality tooling, and continuous
integration. Feature code, database migrations, datasets, model artifacts, and
the frontend have not yet been created.

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

## Data and artifact policy

- Raw third-party data is immutable and is not committed to Git.
- Source URLs, checksums, schema versions, and reproducibility metadata belong in
  `data/manifests/` and may be committed.
- Intermediate and processed datasets are generated locally and ignored.
- Trained model binaries are generated artifacts and ignored.
- Secrets belong in local environment configuration and must never be committed.
- Historical predictions and model metadata will ultimately be persisted as
  immutable, versioned records.

## Documentation

Architecture decisions and component documentation will evolve with the
implementation. See [the architecture index](docs/architecture/README.md).

## Development order

The planned order is:

1. Repository and Python foundation
2. Historical ingestion and canonical data
3. Point-in-time features and Elo
4. Probabilistic match and score models
5. Season simulation and model versioning
6. PostgreSQL persistence and current-provider integration
7. Prediction lifecycle and FastAPI
8. Automation, deployment, and end-to-end backend validation
9. Frontend architecture and implementation
