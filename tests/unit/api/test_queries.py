"""Focused tests for lazy, read-only PostgreSQL API projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

import pytest
from pytest import MonkeyPatch

from pl_platform.api.errors import ApiError
from pl_platform.api.pagination import PaginationParams
from pl_platform.api.queries import (
    PostgresResourceQueryService,
    default_resource_query_service,
)
from pl_platform.api.resources import FixtureStatus
from pl_platform.core.config import Settings
from pl_platform.persistence.repositories import MIGRATION_HEAD

TEAM_ID = UUID("00000000-0000-0000-0000-000000000001")
AWAY_ID = UUID("00000000-0000-0000-0000-000000000002")
FIXTURE_ID = UUID("00000000-0000-0000-0000-000000000003")
PREDICTION_ID = UUID("00000000-0000-0000-0000-000000000004")
MODEL_ID = UUID("00000000-0000-0000-0000-000000000005")
ENTRY_ID = UUID("00000000-0000-0000-0000-000000000006")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000007")
SIMULATION_ID = UUID("00000000-0000-0000-0000-000000000008")
SUMMARY_ID = UUID("00000000-0000-0000-0000-000000000009")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
SHA256 = "a" * 64

TEAM_ROW: dict[str, object] = {
    "team_id": TEAM_ID,
    "slug": "alpha-fc",
    "display_name": "Alpha FC",
    "country_code": "ENG",
    "registry_sha256": SHA256,
}
SEASON_ROW: dict[str, object] = {
    "competition_id": "eng-premier-league",
    "season_id": "2024-2025",
    "starts_on": date(2024, 8, 1),
    "ends_on": date(2025, 5, 31),
    "completed": True,
    "registry_sha256": SHA256,
    "team_count": 1,
}
FIXTURE_ROW: dict[str, object] = {
    "fixture_id": FIXTURE_ID,
    "competition_id": "eng-premier-league",
    "season_id": "2024-2025",
    "home_team_id": TEAM_ID,
    "away_team_id": AWAY_ID,
    "kickoff_at": NOW,
    "kickoff_precision": "exact",
    "status": "finished",
    "matchweek": 1,
    "full_time_home_goals": 2,
    "full_time_away_goals": 1,
    "outcome": "home_win",
}
PREDICTION_ROW: dict[str, object] = {
    "prediction_id": PREDICTION_ID,
    "fixture_id": FIXTURE_ID,
    "competition_id": "eng-premier-league",
    "season_id": "2024-2025",
    "home_team_id": TEAM_ID,
    "away_team_id": AWAY_ID,
    "kickoff_at": NOW,
    "feature_cutoff_at": datetime(2026, 9, 15, 12, tzinfo=UTC),
    "model_id": MODEL_ID,
    "registry_entry_id": ENTRY_ID,
    "registry_head_event_id": EVENT_ID,
    "method": "catboost",
    "method_version": 1,
    "configuration_id": "catboost-depth6-regularized",
    "home_win_probability": 0.5,
    "draw_probability": 0.3,
    "away_win_probability": 0.2,
}
SIMULATION_ROW: dict[str, object] = {
    "simulation_id": SIMULATION_ID,
    "summary_id": SUMMARY_ID,
    "competition_id": "eng-premier-league",
    "season_id": "2024-2025",
    "algorithm_version": 1,
    "simulation_seed": 42,
    "simulation_count": 10_000,
}
MODEL_ROW: dict[str, object] = {
    "model_id": MODEL_ID,
    "competition_id": "eng-premier-league",
    "specification_version": 1,
    "selected_method": "catboost",
    "selected_configuration_id": "catboost-depth6-regularized",
    "selected_calibration": "identity",
    "assessment_accepted": True,
    "registry_state": "development_accepted",
}


class ScriptedResult:
    """Small SQLAlchemy result double used after transaction guards."""

    def __init__(
        self,
        *,
        scalar: object = None,
        rows: Sequence[Mapping[str, object]] = (),
    ) -> None:
        self.scalar = scalar
        self.rows = tuple(rows)

    def scalar_one(self) -> object:
        return self.scalar

    def scalar_one_or_none(self) -> object:
        return self.scalar

    def mappings(self) -> Self:
        return self

    def all(self) -> Sequence[Mapping[str, object]]:
        return self.rows

    def one_or_none(self) -> Mapping[str, object] | None:
        return self.rows[0] if self.rows else None


class NullContext(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class ScriptedConnection(AbstractContextManager["ScriptedConnection"]):
    def __init__(self, results: Sequence[ScriptedResult], revision: object) -> None:
        self.results = list(results)
        self.revision = revision
        self.read_only_seen = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> NullContext:
        return NullContext()

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> ScriptedResult:
        sql = str(statement)
        if sql == "SET TRANSACTION READ ONLY":
            self.read_only_seen = True
            return ScriptedResult()
        if "SELECT version_num FROM alembic_version" in sql:
            return ScriptedResult(scalar=self.revision)
        assert self.read_only_seen
        assert self.results, sql
        return self.results.pop(0)


class ScriptedEngine:
    def __init__(self, results: Sequence[ScriptedResult], revision: object) -> None:
        self.connection = ScriptedConnection(results, revision)
        self.disposed = False

    def connect(self) -> ScriptedConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _settings(environment: str = "test") -> Settings:
    return Settings(environment=environment)  # type: ignore[arg-type]


def _service(
    monkeypatch: MonkeyPatch,
    *results: ScriptedResult,
    revision: object = MIGRATION_HEAD,
) -> tuple[PostgresResourceQueryService, ScriptedEngine]:
    engine = ScriptedEngine(results, revision)

    def create_engine(settings: Settings, *, target: str) -> ScriptedEngine:
        assert settings.environment == "test"
        assert target == "test"
        return engine

    monkeypatch.setattr("pl_platform.api.queries.create_database_engine", create_engine)
    return PostgresResourceQueryService(_settings()), engine


def test_team_and_season_queries_map_deterministic_registry_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    service, engine = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(TEAM_ROW,)),
    )
    teams = service.list_teams(
        season_id="2024-2025", pagination=PaginationParams(limit=1)
    )
    assert teams.items[0].display_name == "Alpha FC"
    assert engine.disposed

    service, _ = _service(monkeypatch, ScriptedResult(rows=(TEAM_ROW,)))
    assert service.get_team(TEAM_ID).team_id == TEAM_ID

    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(SEASON_ROW,)),
    )
    assert service.list_seasons(pagination=PaginationParams()).items[0].completed

    membership = {
        **TEAM_ROW,
        "ordinal": 0,
        "entry_status": "continued",
        "previous_competition_id": None,
    }
    service, _ = _service(
        monkeypatch,
        ScriptedResult(rows=(SEASON_ROW,)),
        ScriptedResult(rows=(membership,)),
    )
    detail = service.get_season("2024-2025")
    assert detail.teams[0].team.team_id == TEAM_ID


def test_fixture_standings_and_prediction_queries_map_only_persisted_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(FIXTURE_ROW,)),
    )
    fixtures = service.list_fixtures(
        season_id="2024-2025",
        team_id=TEAM_ID,
        fixture_status=FixtureStatus.FINISHED,
        pagination=PaginationParams(),
    )
    assert fixtures.items[0].outcome == "home_win"

    service, _ = _service(monkeypatch, ScriptedResult(rows=(FIXTURE_ROW,)))
    assert service.get_fixture(FIXTURE_ID).fixture_id == FIXTURE_ID

    standing_row = {
        **TEAM_ROW,
        "position": 1,
        "played": 1,
        "won": 1,
        "drawn": 0,
        "lost": 0,
        "goals_for": 2,
        "goals_against": 1,
        "goal_difference": 1,
        "points": 3,
        "points_adjustment": 0,
    }
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "competition_id": "eng-premier-league",
        "season_id": "2024-2025",
        "retrieved_at": NOW,
    }
    service, _ = _service(
        monkeypatch,
        ScriptedResult(rows=(snapshot,)),
        ScriptedResult(rows=(standing_row,)),
    )
    assert service.get_standings("2024-2025").rows[0].points == 3

    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(PREDICTION_ROW,)),
    )
    predictions = service.list_predictions(
        season_id="2024-2025",
        team_id=TEAM_ID,
        pagination=PaginationParams(),
    )
    assert predictions.items[0].home_win_probability == 0.5

    service, _ = _service(monkeypatch, ScriptedResult(rows=(PREDICTION_ROW,)))
    assert service.get_prediction(PREDICTION_ID).prediction_id == PREDICTION_ID


def test_simulation_and_model_queries_project_existing_evidence(
    monkeypatch: MonkeyPatch,
) -> None:
    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(SIMULATION_ROW,)),
    )
    simulations = service.list_simulations(
        season_id="2024-2025", pagination=PaginationParams()
    )
    assert simulations.items[0].simulation_count == 10_000

    service, _ = _service(monkeypatch, ScriptedResult(rows=(SIMULATION_ROW,)))
    assert service.get_simulation(SIMULATION_ID).summary_id == SUMMARY_ID

    team_summary = {
        **TEAM_ROW,
        "expected_points": 80.0,
        "expected_goals_for": 70.0,
        "expected_goals_against": 30.0,
        "expected_goal_difference": 40.0,
        "champion_probability": 0.6,
        "top_four_probability": 0.9,
        "top_six_probability": 0.95,
        "relegation_probability": 0.0,
    }
    probability = {"team_id": TEAM_ID, "position": 1, "probability": 0.6}
    service, _ = _service(
        monkeypatch,
        ScriptedResult(rows=(SIMULATION_ROW,)),
        ScriptedResult(rows=(team_summary,)),
        ScriptedResult(rows=(probability,)),
    )
    table = service.get_predicted_table(SIMULATION_ID)
    assert table.rows[0].predicted_position == 1
    assert table.rows[0].position_probabilities[0].probability == 0.6

    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar=1),
        ScriptedResult(rows=(MODEL_ROW,)),
    )
    models = service.list_model_performance(pagination=PaginationParams())
    assert models.items[0].registry_state == "development_accepted"

    metric = {
        "evaluation_dataset_id": "advanced-evaluation",
        "evaluation_manifest_sha256": SHA256,
        "partition_id": None,
        "method": "catboost",
        "configuration_id": "catboost-depth6-regularized",
        "metric_scope": "aggregate",
        "prediction_count": 1900,
        "home_win_count": 800,
        "draw_count": 500,
        "away_win_count": 600,
        "mean_log_loss": 0.9,
        "mean_multiclass_brier_score": 0.5,
        "mean_ranked_probability_score": 0.2,
    }
    service, _ = _service(
        monkeypatch,
        ScriptedResult(rows=(MODEL_ROW,)),
        ScriptedResult(rows=(metric,)),
    )
    performance = service.get_model_performance(MODEL_ID)
    assert performance.evidence_scope == "development"
    assert performance.metrics[0].prediction_count == 1900


def test_query_boundary_fails_closed_for_environment_schema_and_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    production = PostgresResourceQueryService(_settings("production"))
    with pytest.raises(ApiError, match="database_not_configured") as production_error:
        production.list_seasons(pagination=PaginationParams())
    assert production_error.value.status_code == 503

    service, engine = _service(monkeypatch, revision="old-head")
    with pytest.raises(ApiError, match="database_schema_incompatible"):
        service.list_seasons(pagination=PaginationParams())
    assert engine.disposed

    service, _ = _service(
        monkeypatch,
        ScriptedResult(scalar="not-an-integer"),
    )
    with pytest.raises(ApiError, match="database_schema_incompatible"):
        service.list_seasons(pagination=PaginationParams())

    service, _ = _service(monkeypatch, ScriptedResult(rows=()))
    with pytest.raises(ApiError, match="team_not_found"):
        service.get_team(TEAM_ID)

    service, _ = _service(monkeypatch, ScriptedResult(rows=({"bad": "row"},)))
    with pytest.raises(ApiError, match="database_schema_incompatible"):
        service.get_team(TEAM_ID)

    assert isinstance(
        default_resource_query_service(_settings()), PostgresResourceQueryService
    )
