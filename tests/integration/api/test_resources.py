"""Read-only API projection checks against isolated test PostgreSQL."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from pl_platform.api.application import create_app
from pl_platform.core.config import Settings
from pl_platform.persistence.database import create_database_engine

REQUEST_HEADERS = {"X-Request-ID": "integration-resource-test"}
READ_TABLES = (
    "identity.team_registry_member",
    "identity.season_registry_entry",
    "identity.season_membership",
    "football.fixture",
    "football.current_standing_snapshot",
    "prediction.current_model_prediction",
    "simulation.simulation_run",
    "simulation.simulation_summary",
    "ml.evaluation_metric",
    "registry.registry_event",
)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _table_counts(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in READ_TABLES
        )


@pytest.mark.postgresql
def test_resource_endpoints_read_test_projections_without_mutation() -> None:
    settings = Settings(environment="test")
    if settings.test_database_url is None:
        pytest.skip("test PostgreSQL URL is not configured")
    engine = create_database_engine(settings, target="test")
    before_counts = _table_counts(engine)
    before_artifacts = _tree_bytes(settings.artifact_root)
    app = create_app(settings=settings)

    try:
        with TestClient(app) as client:
            responses = {
                path: client.get(path, headers=REQUEST_HEADERS)
                for path in (
                    "/api/v1/teams",
                    "/api/v1/seasons",
                    "/api/v1/fixtures",
                    "/api/v1/predictions",
                    "/api/v1/simulations",
                    "/api/v1/models",
                )
            }
            seasons = responses["/api/v1/seasons"].json()["items"]
            fixtures = responses["/api/v1/fixtures"].json()["items"]
            if seasons:
                season_id = seasons[0]["season_id"]
                season_detail = client.get(
                    f"/api/v1/seasons/{season_id}", headers=REQUEST_HEADERS
                )
                standings = client.get(
                    f"/api/v1/seasons/{season_id}/standings",
                    headers=REQUEST_HEADERS,
                )
                assert season_detail.status_code == 200
                assert standings.status_code in {200, 404}
            if fixtures:
                fixture_detail = client.get(
                    f"/api/v1/fixtures/{fixtures[0]['fixture_id']}",
                    headers=REQUEST_HEADERS,
                )
                assert fixture_detail.status_code == 200
    finally:
        after_counts = _table_counts(engine)
        engine.dispose()

    assert all(response.status_code == 200 for response in responses.values())
    assert all("page" in response.json() for response in responses.values())
    assert after_counts == before_counts
    assert _tree_bytes(settings.artifact_root) == before_artifacts
