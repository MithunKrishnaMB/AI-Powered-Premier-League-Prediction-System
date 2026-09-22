"""Tests for PostgreSQL engine construction and connectivity checks."""

from typing import cast
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from pl_platform.core.config import Settings
from pl_platform.persistence.database import (
    DatabaseConnectionError,
    check_database_connection,
    create_database_engine,
)


def _settings() -> Settings:
    return Settings(
        database_url=SecretStr(
            "postgresql+psycopg://pl_app:development@localhost:5432/pl_dev"
        ),
        test_database_url=SecretStr(
            "postgresql+psycopg://pl_app:test@localhost:5432/pl_test"
        ),
        database_connect_timeout_seconds=7,
        database_pool_size=3,
        database_max_overflow=2,
    )


def _mock_engine(row: tuple[object, ...]) -> Engine:
    engine = MagicMock()
    engine.url = make_url(
        "postgresql+psycopg://pl_app:development@localhost:5432/pl_dev"
    )
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = row
    return cast(Engine, engine)


def test_create_database_engine_is_lazy_and_target_specific() -> None:
    engine = create_database_engine(_settings(), target="test")

    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "pl_test"
        assert engine.url.username == "pl_app"
        assert "test@" not in repr(engine.url)
        assert cast(QueuePool, engine.pool).size() == 3
    finally:
        engine.dispose()


def test_create_database_engine_accepts_explicit_tls_production_target() -> None:
    settings = _settings().model_copy(
        update={
            "production_database_url": SecretStr(
                "postgresql+psycopg://pl_api:production@db.example:5432/pl_prod"
                "?sslmode=require"
            )
        }
    )
    engine = create_database_engine(settings, target="production")

    try:
        assert engine.url.database == "pl_prod"
        assert engine.url.username == "pl_api"
        assert engine.url.query["sslmode"] == "require"
    finally:
        engine.dispose()


def test_check_database_connection_returns_only_non_secret_facts() -> None:
    engine = _mock_engine(
        (
            "pl_dev",
            "pl_app",
            "18.4",
            "180004",
            "UTC",
            True,
            False,
            False,
            False,
            False,
            False,
        )
    )
    result = check_database_connection(engine, target="development")

    assert result.database_name == "pl_dev"
    assert result.database_user == "pl_app"
    assert result.server_version == "18.4"
    assert result.server_version_number == 180004
    assert result.timezone == "UTC"


def test_check_database_connection_rejects_old_postgresql() -> None:
    engine = _mock_engine(
        (
            "pl_dev",
            "pl_app",
            "15.9",
            "150009",
            "UTC",
            True,
            False,
            False,
            False,
            False,
            False,
        )
    )

    with pytest.raises(DatabaseConnectionError, match="16 or newer"):
        check_database_connection(engine, target="development")


def test_check_database_connection_rejects_non_utc_session() -> None:
    engine = _mock_engine(
        (
            "pl_dev",
            "pl_app",
            "18.4",
            "180004",
            "Asia/Kolkata",
            True,
            False,
            False,
            False,
            False,
            False,
        )
    )

    with pytest.raises(DatabaseConnectionError, match="timezone must be UTC"):
        check_database_connection(engine, target="development")


@pytest.mark.parametrize(
    "role_capabilities",
    (
        (False, False, False, False, False, False),
        (True, True, False, False, False, False),
        (True, False, True, False, False, False),
        (True, False, False, True, False, False),
        (True, False, False, False, True, False),
        (True, False, False, False, False, True),
    ),
)
def test_check_database_connection_rejects_non_login_or_privileged_role(
    role_capabilities: tuple[bool, bool, bool, bool, bool, bool],
) -> None:
    engine = _mock_engine(
        ("pl_dev", "pl_app", "18.4", "180004", "UTC", *role_capabilities)
    )

    with pytest.raises(DatabaseConnectionError, match="unprivileged login"):
        check_database_connection(engine, target="development")


def test_check_database_connection_rejects_wrong_connection_identity() -> None:
    engine = _mock_engine(
        (
            "wrong",
            "pl_app",
            "18.4",
            "180004",
            "UTC",
            True,
            False,
            False,
            False,
            False,
            False,
        )
    )
    with pytest.raises(DatabaseConnectionError, match="does not match"):
        check_database_connection(engine, target="development")


def test_check_database_connection_wraps_driver_errors() -> None:
    engine = MagicMock(spec=Engine)
    engine.connect.side_effect = OperationalError("SELECT 1", {}, RuntimeError())

    with pytest.raises(DatabaseConnectionError, match="configured test"):
        check_database_connection(cast(Engine, engine), target="test")


def test_check_database_connection_rejects_invalid_version_number() -> None:
    engine = _mock_engine(
        (
            "pl_dev",
            "pl_app",
            "invalid",
            "not-a-number",
            "UTC",
            True,
            False,
            False,
            False,
            False,
            False,
        )
    )

    with pytest.raises(DatabaseConnectionError, match="unable to connect"):
        check_database_connection(engine, target="development")
