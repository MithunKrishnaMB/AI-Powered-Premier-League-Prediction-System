"""HTTP contract tests for read-only version-one resource endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.api.errors import ApiError
from pl_platform.api.pagination import PaginatedResponse, PaginationParams
from pl_platform.api.resources import (
    EvaluationMetric,
    Fixture,
    FixtureStatus,
    MatchOutcome,
    ModelPerformance,
    ModelPerformanceDetail,
    PositionProbability,
    PredictedTable,
    PredictedTableRow,
    Prediction,
    RegistryState,
    Season,
    SeasonDetail,
    SeasonTeam,
    Simulation,
    StandingRow,
    Standings,
    Team,
)
from pl_platform.core.config import Settings

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
REQUEST_HEADERS = {"X-Request-ID": "resource-contract-test"}


def _team(team_id: UUID = TEAM_ID, name: str = "Alpha FC") -> Team:
    return Team(
        team_id=team_id,
        slug=name.casefold().replace(" ", "-"),
        display_name=name,
        country_code="ENG",
        registry_sha256=SHA256,
    )


TEAM = _team()
AWAY = _team(AWAY_ID, "Beta FC")
SEASON = Season(
    competition_id="eng-premier-league",
    season_id="2024-2025",
    starts_on=date(2024, 8, 1),
    ends_on=date(2025, 5, 31),
    completed=True,
    registry_sha256=SHA256,
    team_count=1,
)
SEASON_DETAIL = SeasonDetail(
    **SEASON.model_dump(),
    teams=(
        SeasonTeam(
            ordinal=0,
            team=TEAM,
            entry_status="continued",
            previous_competition_id=None,
        ),
    ),
)
FIXTURE = Fixture(
    fixture_id=FIXTURE_ID,
    competition_id="eng-premier-league",
    season_id="2024-2025",
    home_team_id=TEAM_ID,
    away_team_id=AWAY_ID,
    kickoff_at=NOW,
    kickoff_precision="exact",
    status=FixtureStatus.FINISHED,
    matchweek=1,
    full_time_home_goals=2,
    full_time_away_goals=1,
    outcome=MatchOutcome.HOME_WIN,
)
STANDINGS = Standings(
    snapshot_id=SNAPSHOT_ID,
    competition_id="eng-premier-league",
    season_id="2024-2025",
    retrieved_at=NOW,
    rows=(
        StandingRow(
            team=TEAM,
            position=1,
            played=1,
            won=1,
            drawn=0,
            lost=0,
            goals_for=2,
            goals_against=1,
            goal_difference=1,
            points=3,
            points_adjustment=0,
        ),
    ),
)
PREDICTION = Prediction(
    prediction_id=PREDICTION_ID,
    fixture_id=FIXTURE_ID,
    competition_id="eng-premier-league",
    season_id="2024-2025",
    home_team_id=TEAM_ID,
    away_team_id=AWAY_ID,
    kickoff_at=NOW,
    feature_cutoff_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    model_id=MODEL_ID,
    registry_entry_id=ENTRY_ID,
    registry_head_event_id=EVENT_ID,
    method="catboost",
    method_version=1,
    configuration_id="catboost-depth6-regularized",
    home_win_probability=0.5,
    draw_probability=0.3,
    away_win_probability=0.2,
)
SIMULATION = Simulation(
    simulation_id=SIMULATION_ID,
    summary_id=SUMMARY_ID,
    competition_id="eng-premier-league",
    season_id="2024-2025",
    algorithm_version=1,
    simulation_seed=42,
    simulation_count=10_000,
)
TABLE = PredictedTable(
    simulation=SIMULATION,
    rows=(
        PredictedTableRow(
            predicted_position=1,
            team=TEAM,
            expected_points=80.0,
            expected_goals_for=70.0,
            expected_goals_against=30.0,
            expected_goal_difference=40.0,
            champion_probability=0.6,
            top_four_probability=0.9,
            top_six_probability=0.95,
            relegation_probability=0.0,
            position_probabilities=(PositionProbability(position=1, probability=0.6),),
        ),
    ),
)
PERFORMANCE = ModelPerformance(
    model_id=MODEL_ID,
    competition_id="eng-premier-league",
    specification_version=1,
    selected_method="catboost",
    selected_configuration_id="catboost-depth6-regularized",
    selected_calibration="identity",
    assessment_accepted=True,
    registry_state=RegistryState.DEVELOPMENT_ACCEPTED,
)
PERFORMANCE_DETAIL = ModelPerformanceDetail(
    **PERFORMANCE.model_dump(),
    metrics=(
        EvaluationMetric(
            evaluation_dataset_id="advanced-evaluation",
            evaluation_manifest_sha256=SHA256,
            partition_id=None,
            method="catboost",
            configuration_id="catboost-depth6-regularized",
            metric_scope="aggregate",
            prediction_count=1900,
            home_win_count=800,
            draw_count=500,
            away_win_count=600,
            mean_log_loss=0.9,
            mean_multiclass_brier_score=0.5,
            mean_ranked_probability_score=0.2,
        ),
    ),
)


def _page[T](item: T, pagination: PaginationParams) -> PaginatedResponse[T]:
    return PaginatedResponse[T].build(items=(item,), params=pagination, total=1)


class StubResourceService:
    """Complete deterministic query stub for router contract tests."""

    def list_teams(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Team]:
        assert season_id in {None, "2024-2025"}
        return _page(TEAM, pagination)

    def get_team(self, team_id: UUID) -> Team:
        assert team_id == TEAM_ID
        return TEAM

    def list_seasons(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[Season]:
        return _page(SEASON, pagination)

    def get_season(self, season_id: str) -> SeasonDetail:
        assert season_id == "2024-2025"
        return SEASON_DETAIL

    def list_fixtures(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        fixture_status: FixtureStatus | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Fixture]:
        assert (season_id, team_id, fixture_status) == (
            "2024-2025",
            TEAM_ID,
            FixtureStatus.FINISHED,
        )
        return _page(FIXTURE, pagination)

    def get_fixture(self, fixture_id: UUID) -> Fixture:
        assert fixture_id == FIXTURE_ID
        return FIXTURE

    def get_standings(self, season_id: str) -> Standings:
        assert season_id == "2024-2025"
        return STANDINGS

    def list_predictions(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Prediction]:
        assert (season_id, team_id) == ("2024-2025", TEAM_ID)
        return _page(PREDICTION, pagination)

    def get_prediction(self, prediction_id: UUID) -> Prediction:
        assert prediction_id == PREDICTION_ID
        return PREDICTION

    def list_simulations(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Simulation]:
        assert season_id == "2024-2025"
        return _page(SIMULATION, pagination)

    def get_simulation(self, simulation_id: UUID) -> Simulation:
        assert simulation_id == SIMULATION_ID
        return SIMULATION

    def get_predicted_table(self, simulation_id: UUID) -> PredictedTable:
        assert simulation_id == SIMULATION_ID
        return TABLE

    def list_model_performance(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[ModelPerformance]:
        return _page(PERFORMANCE, pagination)

    def get_model_performance(self, model_id: UUID) -> ModelPerformanceDetail:
        if model_id != MODEL_ID:
            raise ApiError(
                status_code=404,
                code="model_not_found",
                message="Model not found.",
            )
        return PERFORMANCE_DETAIL


def _client() -> TestClient:
    return TestClient(create_app(settings=Settings(), resources=StubResourceService()))


def test_team_and_season_routes_are_versioned_paginated_and_stable() -> None:
    with _client() as client:
        teams = client.get(
            "/api/v1/teams?season_id=2024-2025&limit=1",
            headers=REQUEST_HEADERS,
        )
        team = client.get(f"/api/v1/teams/{TEAM_ID}", headers=REQUEST_HEADERS)
        seasons = client.get("/api/v1/seasons?limit=1", headers=REQUEST_HEADERS)
        season = client.get("/api/v1/seasons/2024-2025", headers=REQUEST_HEADERS)

    assert teams.status_code == team.status_code == 200
    assert seasons.status_code == season.status_code == 200
    assert teams.json()["items"][0]["display_name"] == "Alpha FC"
    assert teams.json()["page"]["total"] == 1
    assert team.json()["team_id"] == str(TEAM_ID)
    assert season.json()["teams"][0]["entry_status"] == "continued"


def test_fixture_standings_and_prediction_routes_return_only_stored_values() -> None:
    with _client() as client:
        fixtures = client.get(
            f"/api/v1/fixtures?season_id=2024-2025&team_id={TEAM_ID}&status=finished",
            headers=REQUEST_HEADERS,
        )
        fixture = client.get(f"/api/v1/fixtures/{FIXTURE_ID}", headers=REQUEST_HEADERS)
        standings = client.get(
            "/api/v1/seasons/2024-2025/standings", headers=REQUEST_HEADERS
        )
        predictions = client.get(
            f"/api/v1/predictions?season_id=2024-2025&team_id={TEAM_ID}",
            headers=REQUEST_HEADERS,
        )
        prediction = client.get(
            f"/api/v1/predictions/{PREDICTION_ID}", headers=REQUEST_HEADERS
        )

    assert fixtures.status_code == fixture.status_code == 200
    assert (
        standings.status_code
        == predictions.status_code
        == prediction.status_code
        == 200
    )
    assert fixture.json()["full_time_home_goals"] == 2
    assert standings.json()["rows"][0]["points"] == 3
    assert predictions.json()["items"][0]["home_win_probability"] == 0.5
    assert "scoreline" not in prediction.json()


def test_simulation_and_development_performance_routes_do_not_execute_workflows() -> (
    None
):
    with _client() as client:
        simulations = client.get(
            "/api/v1/simulations?season_id=2024-2025", headers=REQUEST_HEADERS
        )
        simulation = client.get(
            f"/api/v1/simulations/{SIMULATION_ID}", headers=REQUEST_HEADERS
        )
        table = client.get(
            f"/api/v1/simulations/{SIMULATION_ID}/predicted-table",
            headers=REQUEST_HEADERS,
        )
        models = client.get("/api/v1/models", headers=REQUEST_HEADERS)
        performance = client.get(
            f"/api/v1/models/{MODEL_ID}/performance", headers=REQUEST_HEADERS
        )

    assert simulations.status_code == simulation.status_code == table.status_code == 200
    assert models.status_code == performance.status_code == 200
    assert table.json()["rows"][0]["predicted_position"] == 1
    assert models.json()["items"][0]["registry_state"] == "development_accepted"
    assert performance.json()["evidence_scope"] == "development"
    assert performance.json()["metrics"][0]["metric_scope"] == "aggregate"


def test_resource_validation_and_not_found_use_shared_error_envelope() -> None:
    with _client() as client:
        invalid = client.get("/api/v1/seasons/not-a-season", headers=REQUEST_HEADERS)
        missing = client.get(
            "/api/v1/models/00000000-0000-0000-0000-000000000099/performance",
            headers=REQUEST_HEADERS,
        )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "model_not_found"
