"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object per process."""

    return Settings()
