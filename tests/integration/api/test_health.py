"""Read-only health checks against test PostgreSQL and the actual registry."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.core.config import Settings


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.postgresql
def test_real_readiness_uses_test_database_and_preserves_no_active_registry() -> None:
    settings = Settings(environment="test")
    if settings.test_database_url is None:
        pytest.skip("test PostgreSQL URL is not configured")
    before = _tree_bytes(settings.artifact_root)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.get(
            "/health/ready",
            headers={"X-Request-ID": "integration-health-test"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "schema_version": 1,
        "status": "not_ready",
        "dependencies": [
            {"name": "postgresql", "status": "ready", "reason": None},
            {
                "name": "active_model",
                "status": "not_ready",
                "reason": "no_active_model",
            },
        ],
    }
    assert _tree_bytes(settings.artifact_root) == before
