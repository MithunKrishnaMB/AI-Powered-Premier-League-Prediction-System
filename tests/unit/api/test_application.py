"""Tests for explicit, side-effect-free FastAPI construction."""

from __future__ import annotations

import subprocess
import sys

from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.api.health import (
    DependencyHealth,
    DependencyName,
    DependencyStatus,
    ReadinessService,
)
from pl_platform.core.config import Settings
from tests.unit.api.helpers import StaticProbe

REQUEST_ID = "application-test-request"


def _ready_service() -> ReadinessService:
    return ReadinessService(
        probes=(
            StaticProbe(
                DependencyName.POSTGRESQL,
                DependencyHealth(
                    name=DependencyName.POSTGRESQL,
                    status=DependencyStatus.READY,
                    reason=None,
                ),
            ),
            StaticProbe(
                DependencyName.ACTIVE_MODEL,
                DependencyHealth(
                    name=DependencyName.ACTIVE_MODEL,
                    status=DependencyStatus.READY,
                    reason=None,
                ),
            ),
        )
    )


def test_import_does_not_construct_an_app_or_load_runtime_dependencies() -> None:
    script = """
import pl_platform.core.config as config
import pl_platform.persistence.database as database
import pl_platform.registry.active_model as active_model

def fail(*args, **kwargs):
    raise AssertionError("import performed runtime work")

config.get_settings = fail
database.create_database_engine = fail
active_model.load_current_active_model = fail
import pl_platform.api.application
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_factory_registers_routes_without_running_probes_or_queries() -> None:
    service = ReadinessService(
        probes=(
            StaticProbe(
                DependencyName.POSTGRESQL,
                error=AssertionError("probe ran during construction"),
            ),
        )
    )
    app = create_app(settings=Settings(), readiness=service)
    with TestClient(app) as client:
        live = client.get("/health/live", headers={"X-Request-ID": REQUEST_ID})
        root = client.get("/", headers={"X-Request-ID": REQUEST_ID})
        docs = client.get("/docs", headers={"X-Request-ID": REQUEST_ID})
        openapi = client.get("/openapi.json", headers={"X-Request-ID": REQUEST_ID})

    assert live.status_code == 200
    assert root.status_code == docs.status_code == openapi.status_code == 404


def test_health_responses_use_the_declared_factory_contract() -> None:
    app = create_app(settings=Settings(app_name="Test API"), readiness=_ready_service())
    with TestClient(app) as client:
        live = client.get("/health/live", headers={"X-Request-ID": REQUEST_ID})
        ready = client.get("/health/ready", headers={"X-Request-ID": REQUEST_ID})

    assert app.title == "Test API"
    assert app.openapi_url is None
    assert live.status_code == 200
    assert live.json() == {"schema_version": 1, "status": "alive"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
