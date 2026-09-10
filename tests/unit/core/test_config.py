"""Tests for typed environment configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pl_platform.core.config import Settings, get_settings


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


def test_settings_read_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLP_ENVIRONMENT", "test")
    monkeypatch.setenv("PLP_DEBUG", "true")
    monkeypatch.setenv("PLP_LOG_LEVEL", "WARNING")

    settings = Settings()

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.log_level == "WARNING"


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLP_LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()
