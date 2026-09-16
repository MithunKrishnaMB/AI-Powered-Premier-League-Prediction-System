"""Public OpenAPI contract for the completed read-only API surface."""

from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.core.config import Settings

EXPECTED_OPERATIONS = {
    "/health/live": "get_liveness",
    "/health/ready": "get_readiness",
    "/api/v1/teams": "list_teams",
    "/api/v1/teams/{team_id}": "get_team",
    "/api/v1/seasons": "list_seasons",
    "/api/v1/seasons/{season_id}": "get_season",
    "/api/v1/fixtures": "list_fixtures",
    "/api/v1/fixtures/{fixture_id}": "get_fixture",
    "/api/v1/seasons/{season_id}/standings": "get_standings",
    "/api/v1/predictions": "list_predictions",
    "/api/v1/predictions/{prediction_id}": "get_prediction",
    "/api/v1/simulations": "list_simulations",
    "/api/v1/simulations/{simulation_id}": "get_simulation",
    "/api/v1/simulations/{simulation_id}/predicted-table": "get_predicted_table",
    "/api/v1/models": "list_model_performance",
    "/api/v1/models/{model_id}/performance": "get_model_performance",
}


def test_openapi_paths_operations_and_error_contract_are_stable() -> None:
    app = create_app(settings=Settings(rate_limit_enabled=False))
    with TestClient(app) as client:
        response = client.get(
            "/openapi.json",
            headers={"X-Request-ID": "openapi-contract-test"},
        )
        docs = client.get("/docs", headers={"X-Request-ID": "docs-contract-test"})

    assert response.status_code == docs.status_code == 200
    document = response.json()
    assert document["openapi"] == "3.1.0"
    assert document["info"] == {
        "title": "Premier League Prediction Platform",
        "description": (
            "Read-only Premier League identity, fixture, prediction, "
            "simulation and development-performance projections."
        ),
        "version": "0.1.0",
    }
    assert set(document["paths"]) == set(EXPECTED_OPERATIONS)

    operation_ids: list[str] = []
    for path, operation_id in EXPECTED_OPERATIONS.items():
        path_item = document["paths"][path]
        assert set(path_item) == {"get"}
        assert path_item["get"]["operationId"] == operation_id
        operation_ids.append(operation_id)
    assert len(operation_ids) == len(set(operation_ids))

    team_responses = document["paths"]["/api/v1/teams"]["get"]["responses"]
    assert set(team_responses) == {
        "200",
        "400",
        "403",
        "404",
        "422",
        "429",
        "500",
        "503",
    }
    assert team_responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert "Team" in document["components"]["schemas"]
    assert "PredictedTable" in document["components"]["schemas"]
    assert "ModelPerformanceDetail" in document["components"]["schemas"]


def test_openapi_exposes_no_mutating_operation() -> None:
    document = create_app(settings=Settings(rate_limit_enabled=False)).openapi()

    for path_item in document["paths"].values():
        assert not {"post", "put", "patch", "delete"} & set(path_item)
