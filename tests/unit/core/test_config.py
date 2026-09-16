"""Tests for typed environment configuration."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from pl_platform.core.config import (
    DatabaseConfigurationError,
    Settings,
    get_settings,
)


def test_settings_use_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLP_ENVIRONMENT", raising=False)
    monkeypatch.delenv("PLP_DEBUG", raising=False)
    monkeypatch.delenv("PLP_LOG_LEVEL", raising=False)

    settings = Settings()

    assert settings.environment == "development"
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.artifact_root == Path("artifacts")
    assert settings.registry_root == Path("artifacts/registry")


def test_settings_read_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLP_ENVIRONMENT", "test")
    monkeypatch.setenv("PLP_DEBUG", "true")
    monkeypatch.setenv("PLP_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("PLP_ARTIFACT_ROOT", "runtime-artifacts")
    monkeypatch.setenv("PLP_REGISTRY_ROOT", "runtime-registry")

    settings = Settings()

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.log_level == "WARNING"
    assert settings.artifact_root == Path("runtime-artifacts")
    assert settings.registry_root == Path("runtime-registry")


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLP_LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()


def test_database_urls_are_secret_and_environment_specific() -> None:
    settings = Settings(
        database_url=SecretStr(
            "postgresql+psycopg://pl_app:development@localhost:5432/pl_dev"
        ),
        test_database_url=SecretStr(
            "postgresql+psycopg://pl_app:test@localhost:5432/pl_test"
        ),
    )

    assert "development" not in repr(settings.database_url)
    assert settings.database_url_for("development").endswith("/pl_dev")
    assert settings.database_url_for("test").endswith("/pl_test")


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://pl_app:secret@localhost:5432/pl_dev",
        "postgresql+psycopg://localhost:5432/pl_dev",
        "postgresql+psycopg://pl_app:secret@localhost/pl_dev",
        "postgresql+psycopg://pl_app:secret@localhost:5432",
    ),
)
def test_database_urls_reject_incomplete_or_wrong_driver_urls(
    database_url: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr(database_url))


def test_database_targets_must_not_share_a_database() -> None:
    development_url = "postgresql+psycopg://pl_app:development@LOCALHOST:5432/pl_shared"
    test_url = "postgresql+psycopg://test_app:test@localhost:5432/pl_shared"

    with pytest.raises(ValidationError, match="targets must differ"):
        Settings(
            database_url=SecretStr(development_url),
            test_database_url=SecretStr(test_url),
        )


def test_missing_database_target_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings()

    with pytest.raises(DatabaseConfigurationError, match="test database URL"):
        settings.database_url_for("test")
