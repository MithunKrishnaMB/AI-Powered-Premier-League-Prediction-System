"""Tests for liveness and fail-closed dependency readiness."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

import pl_platform.registry.active_model as active_model_module
from pl_platform.api.health import (
    ActiveModelReadinessProbe,
    DependencyHealth,
    DependencyName,
    DependencyStatus,
    PostgreSQLReadinessProbe,
    ReadinessService,
    ReadinessStatus,
    default_readiness_service,
)
from pl_platform.core.config import Environment, Settings
from pl_platform.registry.active_model import (
    ActiveModelFailureCode,
    ActiveModelLoadError,
)
from tests.unit.api.helpers import StaticProbe


def _settings(*, environment: Environment = "development") -> Settings:
    return Settings(
        environment=environment,
        database_url=SecretStr(
            "postgresql+psycopg://pl_app:development@localhost:5432/pl_dev"
        ),
        test_database_url=SecretStr(
            "postgresql+psycopg://pl_app:test@localhost:5432/pl_test"
        ),
    )


def _dependency(
    name: DependencyName,
    status: DependencyStatus,
    reason: str | None,
) -> DependencyHealth:
    return DependencyHealth(name=name, status=status, reason=reason)


def _engine_at(revision: str | None) -> Engine:
    engine = MagicMock(spec=Engine)
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one_or_none.return_value = revision
    return cast(Engine, engine)


def test_dependency_health_requires_a_reason_only_when_not_ready() -> None:
    with pytest.raises(ValidationError, match="ready dependency"):
        DependencyHealth(
            name=DependencyName.POSTGRESQL,
            status=DependencyStatus.READY,
            reason="unexpected",
        )
    with pytest.raises(ValidationError, match="requires a failure reason"):
        DependencyHealth(
            name=DependencyName.POSTGRESQL,
            status=DependencyStatus.NOT_READY,
            reason=None,
        )


def test_readiness_is_ordered_and_fails_closed() -> None:
    database = _dependency(
        DependencyName.POSTGRESQL,
        DependencyStatus.READY,
        None,
    )
    model = _dependency(
        DependencyName.ACTIVE_MODEL,
        DependencyStatus.NOT_READY,
        "no_active_model",
    )
    service = ReadinessService(
        probes=(
            StaticProbe(DependencyName.POSTGRESQL, database),
            StaticProbe(DependencyName.ACTIVE_MODEL, model),
        )
    )

    result = service.evaluate()

    assert result.status is ReadinessStatus.NOT_READY
    assert result.dependencies == (database, model)


def test_probe_exceptions_and_wrong_names_are_sanitized() -> None:
    wrong = _dependency(
        DependencyName.ACTIVE_MODEL,
        DependencyStatus.READY,
        None,
    )
    service = ReadinessService(
        probes=(
            StaticProbe(DependencyName.POSTGRESQL, error=RuntimeError("secret")),
            StaticProbe(DependencyName.POSTGRESQL, result=wrong),
        )
    )

    result = service.evaluate()

    assert tuple(item.reason for item in result.dependencies) == (
        "dependency_check_failed",
        "dependency_check_failed",
    )


def test_default_probe_order_is_stable() -> None:
    service = default_readiness_service(_settings())

    assert tuple(probe.name for probe in service.probes) == (
        DependencyName.POSTGRESQL,
        DependencyName.ACTIVE_MODEL,
    )


def test_production_database_probe_fails_without_fallback() -> None:
    result = PostgreSQLReadinessProbe(_settings(environment="production")).check()

    assert result.reason == "production_database_not_configured"


def test_database_probe_selects_test_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine_at("f0009_step_7_9")
    selected: list[str] = []

    def create_engine(settings: Settings, *, target: str) -> Engine:
        del settings
        selected.append(target)
        return engine

    monkeypatch.setattr(
        "pl_platform.api.health.create_database_engine",
        create_engine,
    )
    monkeypatch.setattr(
        "pl_platform.api.health.check_database_connection",
        lambda engine, *, target: None,
    )

    result = PostgreSQLReadinessProbe(_settings(environment="test")).check()

    assert result.status is DependencyStatus.READY
    assert selected == ["test"]
    cast(MagicMock, engine).dispose.assert_called_once_with()


def test_database_probe_reports_configuration_connection_and_schema_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = Settings(
        environment="test",
        database_url=None,
        test_database_url=None,
    )
    assert PostgreSQLReadinessProbe(missing).check().reason == "database_not_configured"

    def unavailable(settings: Settings, *, target: str) -> Engine:
        del settings, target
        raise OperationalError("connect", {}, RuntimeError("unavailable"))

    monkeypatch.setattr(
        "pl_platform.api.health.create_database_engine",
        unavailable,
    )
    assert (
        PostgreSQLReadinessProbe(_settings()).check().reason == "database_unavailable"
    )

    engine = _engine_at("old_head")
    monkeypatch.setattr(
        "pl_platform.api.health.create_database_engine",
        lambda settings, *, target: engine,
    )
    monkeypatch.setattr(
        "pl_platform.api.health.check_database_connection",
        lambda engine, *, target: None,
    )
    assert (
        PostgreSQLReadinessProbe(_settings()).check().reason
        == "database_schema_incompatible"
    )


def test_active_model_probe_preserves_stable_failure_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_active_model(**kwargs: object) -> None:
        del kwargs
        raise ActiveModelLoadError(
            ActiveModelFailureCode.NO_ACTIVE_MODEL,
            "synthetic no-active state",
        )

    monkeypatch.setattr(
        active_model_module,
        "load_current_active_model",
        no_active_model,
    )
    failed = ActiveModelReadinessProbe(_settings()).check()
    monkeypatch.setattr(
        active_model_module,
        "load_current_active_model",
        lambda **kwargs: object(),
    )
    ready = ActiveModelReadinessProbe(_settings()).check()

    assert failed.reason == "no_active_model"
    assert ready.status is DependencyStatus.READY
