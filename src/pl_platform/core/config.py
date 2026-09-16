"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DatabaseTarget = Literal["development", "test"]


class DatabaseConfigurationError(ValueError):
    """Database settings are missing or would cross environment boundaries."""


def _database_url_value(value: SecretStr | str) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def _validate_database_url(value: SecretStr | str) -> SecretStr:
    raw_value = _database_url_value(value)
    parsed = urlsplit(raw_value)
    if parsed.scheme != "postgresql+psycopg":
        msg = "database URLs must use the postgresql+psycopg scheme"
        raise ValueError(msg)
    if (
        parsed.hostname is None
        or parsed.port is None
        or parsed.username is None
        or parsed.password is None
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        msg = "database URLs require host, port, user, password and database name"
        raise ValueError(msg)
    return SecretStr(raw_value)


def _database_target_identity(value: SecretStr) -> tuple[str, int, str]:
    parsed = urlsplit(value.get_secret_value())
    hostname = parsed.hostname
    port = parsed.port
    if hostname is None or port is None:
        msg = "validated database URL lost its host or port"
        raise DatabaseConfigurationError(msg)
    return hostname.casefold(), port, unquote(parsed.path.removeprefix("/"))


class Settings(BaseSettings):
    """Process configuration with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PLP_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_name: str = "Premier League Prediction Platform"
    environment: Environment = "development"
    debug: bool = False
    log_level: LogLevel = "INFO"
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    artifact_root: Path = Path("artifacts")
    registry_root: Path = Path("artifacts/registry")
    cors_allowed_origins: tuple[str, ...] = ()
    cors_allow_credentials: bool = False
    cors_max_age_seconds: int = Field(default=600, ge=0, le=86_400)
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=120, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    rate_limit_max_clients: int = Field(default=10_000, ge=1, le=100_000)

    @field_validator("database_url", "test_database_url", mode="before")
    @classmethod
    def database_urls_must_be_explicit_psycopg_urls(
        cls,
        value: SecretStr | str | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        return _validate_database_url(value)

    @field_validator("cors_allowed_origins")
    @classmethod
    def cors_origins_must_be_exact_http_origins(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        for origin in value:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                msg = "CORS origins must be exact HTTP or HTTPS origins"
                raise ValueError(msg)
            host = parsed.hostname.casefold()
            if ":" in host:
                host = f"[{host}]"
            port = f":{parsed.port}" if parsed.port is not None else ""
            canonical = f"{parsed.scheme}://{host}{port}"
            if canonical in normalized:
                msg = "CORS origins must be unique"
                raise ValueError(msg)
            normalized.append(canonical)
        return tuple(normalized)

    @model_validator(mode="after")
    def database_targets_must_be_distinct(self) -> Self:
        if self.database_url is not None and self.test_database_url is not None:
            development = _database_target_identity(self.database_url)
            test = _database_target_identity(self.test_database_url)
            if development == test:
                msg = "development and test database targets must differ"
                raise ValueError(msg)
        return self

    def database_url_for(self, target: DatabaseTarget) -> str:
        """Return one configured URL without exposing it through object repr."""

        # Keep target selection explicit so tests can never fall back to the
        # development database.
        configured = self.test_database_url if target == "test" else self.database_url
        if configured is None:
            msg = f"{target} database URL is not configured"
            raise DatabaseConfigurationError(msg)
        return configured.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object per process."""

    return Settings()
