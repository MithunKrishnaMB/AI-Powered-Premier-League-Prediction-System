"""Version-one read-only football and model resource routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from pl_platform.api.pagination import PaginatedResponse, PaginationParams
from pl_platform.api.queries import ResourceQueryService
from pl_platform.api.resources import (
    Fixture,
    FixtureStatus,
    ModelPerformance,
    ModelPerformanceDetail,
    PredictedTable,
    Prediction,
    Season,
    SeasonDetail,
    Simulation,
    Standings,
    Team,
)

SeasonId = Annotated[str, Path(pattern=r"^[0-9]{4}-[0-9]{4}$")]
OptionalSeasonId = Annotated[
    str | None,
    Query(pattern=r"^[0-9]{4}-[0-9]{4}$"),
]
Page = Annotated[PaginationParams, Depends()]


def create_resource_router(service: ResourceQueryService) -> APIRouter:
    """Bind the injected query boundary to stable version-one routes."""

    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/teams",
        operation_id="list_teams",
        response_model=PaginatedResponse[Team],
        tags=["teams"],
    )
    def list_teams(
        pagination: Page,
        season_id: OptionalSeasonId = None,
    ) -> PaginatedResponse[Team]:
        return service.list_teams(season_id=season_id, pagination=pagination)

    @router.get(
        "/teams/{team_id}",
        operation_id="get_team",
        response_model=Team,
        tags=["teams"],
    )
    def get_team(team_id: UUID) -> Team:
        return service.get_team(team_id)

    @router.get(
        "/seasons",
        operation_id="list_seasons",
        response_model=PaginatedResponse[Season],
        tags=["seasons"],
    )
    def list_seasons(pagination: Page) -> PaginatedResponse[Season]:
        return service.list_seasons(pagination=pagination)

    @router.get(
        "/seasons/{season_id}",
        operation_id="get_season",
        response_model=SeasonDetail,
        tags=["seasons"],
    )
    def get_season(season_id: SeasonId) -> SeasonDetail:
        return service.get_season(season_id)

    @router.get(
        "/fixtures",
        operation_id="list_fixtures",
        response_model=PaginatedResponse[Fixture],
        tags=["fixtures"],
    )
    def list_fixtures(
        pagination: Page,
        season_id: OptionalSeasonId = None,
        team_id: UUID | None = None,
        fixture_status: Annotated[FixtureStatus | None, Query(alias="status")] = None,
    ) -> PaginatedResponse[Fixture]:
        return service.list_fixtures(
            season_id=season_id,
            team_id=team_id,
            fixture_status=fixture_status,
            pagination=pagination,
        )

    @router.get(
        "/fixtures/{fixture_id}",
        operation_id="get_fixture",
        response_model=Fixture,
        tags=["fixtures"],
    )
    def get_fixture(fixture_id: UUID) -> Fixture:
        return service.get_fixture(fixture_id)

    @router.get(
        "/seasons/{season_id}/standings",
        operation_id="get_standings",
        response_model=Standings,
        tags=["standings"],
    )
    def get_standings(season_id: SeasonId) -> Standings:
        return service.get_standings(season_id)

    @router.get(
        "/predictions",
        operation_id="list_predictions",
        response_model=PaginatedResponse[Prediction],
        tags=["predictions"],
    )
    def list_predictions(
        pagination: Page,
        season_id: OptionalSeasonId = None,
        team_id: UUID | None = None,
    ) -> PaginatedResponse[Prediction]:
        return service.list_predictions(
            season_id=season_id,
            team_id=team_id,
            pagination=pagination,
        )

    @router.get(
        "/predictions/{prediction_id}",
        operation_id="get_prediction",
        response_model=Prediction,
        tags=["predictions"],
    )
    def get_prediction(prediction_id: UUID) -> Prediction:
        return service.get_prediction(prediction_id)

    @router.get(
        "/simulations",
        operation_id="list_simulations",
        response_model=PaginatedResponse[Simulation],
        tags=["simulations"],
    )
    def list_simulations(
        pagination: Page,
        season_id: OptionalSeasonId = None,
    ) -> PaginatedResponse[Simulation]:
        return service.list_simulations(season_id=season_id, pagination=pagination)

    @router.get(
        "/simulations/{simulation_id}",
        operation_id="get_simulation",
        response_model=Simulation,
        tags=["simulations"],
    )
    def get_simulation(simulation_id: UUID) -> Simulation:
        return service.get_simulation(simulation_id)

    @router.get(
        "/simulations/{simulation_id}/predicted-table",
        operation_id="get_predicted_table",
        response_model=PredictedTable,
        tags=["simulations"],
    )
    def get_predicted_table(simulation_id: UUID) -> PredictedTable:
        return service.get_predicted_table(simulation_id)

    @router.get(
        "/models",
        operation_id="list_model_performance",
        response_model=PaginatedResponse[ModelPerformance],
        tags=["models"],
    )
    def list_model_performance(pagination: Page) -> PaginatedResponse[ModelPerformance]:
        return service.list_model_performance(pagination=pagination)

    @router.get(
        "/models/{model_id}/performance",
        operation_id="get_model_performance",
        response_model=ModelPerformanceDetail,
        tags=["models"],
    )
    def get_model_performance(model_id: UUID) -> ModelPerformanceDetail:
        return service.get_model_performance(model_id)

    return router
