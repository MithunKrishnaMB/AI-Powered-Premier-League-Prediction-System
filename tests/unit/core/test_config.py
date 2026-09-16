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
    assert settings.cors_allowed_origins == ()
    assert settings.cors_allow_credentials is False
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_requests == 120
    assert settings.rate_limit_window_seconds == 60
    assert settings.rate_limit_max_clients == 10_000


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


def test_browser_transport_settings_are_typed_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "PLP_CORS_ALLOWED_ORIGINS",
        '["https://APP.example/", "http://localhost:3000"]',
    )
    monkeypatch.setenv("PLP_CORS_ALLOW_CREDENTIALS", "true")
    monkeypatch.setenv("PLP_RATE_LIMIT_REQUESTS", "25")
    monkeypatch.setenv("PLP_RATE_LIMIT_WINDOW_SECONDS", "30")

    settings = Settings()

    assert settings.cors_allowed_origins == (
        "https://app.example",
        "http://localhost:3000",
    )
    assert settings.cors_allow_credentials is True
    assert settings.rate_limit_requests == 25
    assert settings.rate_limit_window_seconds == 30


@pytest.mark.parametrize(
    "origins",
    (
        ("*",),
        ("https://user@example.com",),
        ("https://example.com/path",),
        ("https://example.com?query=yes",),
        ("https://example.com", "https://EXAMPLE.com/"),
    ),
)
def test_cors_origins_reject_wildcards_credentials_paths_and_duplicates(
    origins: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        Settings(cors_allowed_origins=origins)


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
