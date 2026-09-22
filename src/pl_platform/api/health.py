"""Side-effect-free liveness and fail-closed readiness boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pl_platform.core.config import (
    DatabaseConfigurationError,
    DatabaseTarget,
    Settings,
)
from pl_platform.persistence.database import (
    DatabaseConnectionError,
    check_database_connection,
    create_database_engine,
)


class HealthModel(BaseModel):
    """Strict immutable base for public health contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DependencyName(StrEnum):
    """Required runtime dependencies in deterministic response order."""

    POSTGRESQL = "postgresql"
    ACTIVE_MODEL = "active_model"


class DependencyStatus(StrEnum):
    """Readiness state for one required dependency."""

    READY = "ready"
    NOT_READY = "not_ready"


class ReadinessStatus(StrEnum):
    """Aggregate application readiness state."""

    READY = "ready"
    NOT_READY = "not_ready"


class DependencyHealth(HealthModel):
    """Sanitized result for one dependency probe."""

    name: DependencyName
    status: DependencyStatus
    reason: str | None

    @model_validator(mode="after")
    def reason_matches_status(self) -> DependencyHealth:
        if self.status is DependencyStatus.READY and self.reason is not None:
            msg = "a ready dependency cannot include a failure reason"
            raise ValueError(msg)
        if self.status is DependencyStatus.NOT_READY and self.reason is None:
            msg = "a dependency that is not ready requires a failure reason"
            raise ValueError(msg)
        return self


class LivenessResponse(HealthModel):
    """Stable response proving only that the ASGI process can answer."""

    schema_version: Literal[1] = 1
    status: Literal["alive"] = "alive"


class ReadinessResponse(HealthModel):
    """Stable aggregate of every required runtime dependency."""

    schema_version: Literal[1] = 1
    status: ReadinessStatus
    dependencies: tuple[DependencyHealth, ...]


class DependencyProbe(Protocol):
    """One named, read-only dependency check."""

    @property
    def name(self) -> DependencyName:
        """Return the stable public dependency name."""

    def check(self) -> DependencyHealth:
        """Return a sanitized readiness result without raising."""


def _ready(name: DependencyName) -> DependencyHealth:
    return DependencyHealth(name=name, status=DependencyStatus.READY, reason=None)


def _not_ready(name: DependencyName, reason: str) -> DependencyHealth:
    return DependencyHealth(
        name=name,
        status=DependencyStatus.NOT_READY,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class PostgreSQLReadinessProbe:
    """Validate one explicitly selected PostgreSQL target and schema head."""

    settings: Settings
    name: DependencyName = DependencyName.POSTGRESQL

    def check(self) -> DependencyHealth:
        if (
            self.settings.environment == "production"
            and self.settings.production_database_url is None
        ):
            return _not_ready(self.name, "production_database_not_configured")
        target: DatabaseTarget = (
            "production"
            if self.settings.environment == "production"
            else "test"
            if self.settings.environment == "test"
            else "development"
        )
        engine = None
        try:
            engine = create_database_engine(self.settings, target=target)
            check_database_connection(engine, target=target)
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        except DatabaseConfigurationError:
            return _not_ready(self.name, "database_not_configured")
        except DatabaseConnectionError, SQLAlchemyError, TypeError, ValueError:
            return _not_ready(self.name, "database_unavailable")
        finally:
            if engine is not None:
                engine.dispose()

        from pl_platform.persistence.repositories import MIGRATION_HEAD

        if revision != MIGRATION_HEAD:
            return _not_ready(self.name, "database_schema_incompatible")
        return _ready(self.name)


@dataclass(frozen=True, slots=True)
class ActiveModelReadinessProbe:
    """Resolve the existing strict active-model boundary only on demand."""

    settings: Settings
    name: DependencyName = DependencyName.ACTIVE_MODEL

    def check(self) -> DependencyHealth:
        # Keep CatBoost and registry loading outside application-module import.
        from pl_platform.registry.active_model import (
            ActiveModelLoadError,
            load_current_active_model,
        )

        try:
            load_current_active_model(
                registry_root=self.settings.registry_root,
                artifact_root=self.settings.artifact_root,
            )
        except ActiveModelLoadError as exc:
            return _not_ready(self.name, exc.code.value)
        return _ready(self.name)


@dataclass(frozen=True, slots=True)
class ReadinessService:
    """Evaluate required probes in their declared deterministic order."""

    probes: tuple[DependencyProbe, ...]

    def evaluate(self) -> ReadinessResponse:
        results: list[DependencyHealth] = []
        for probe in self.probes:
            try:
                result = probe.check()
            except Exception:  # A health boundary must fail closed and stay sanitized.
                result = _not_ready(probe.name, "dependency_check_failed")
            if result.name is not probe.name:
                result = _not_ready(probe.name, "dependency_check_failed")
            results.append(result)
        dependencies = tuple(results)
        overall = (
            ReadinessStatus.READY
            if all(item.status is DependencyStatus.READY for item in dependencies)
            else ReadinessStatus.NOT_READY
        )
        return ReadinessResponse(status=overall, dependencies=dependencies)


def default_readiness_service(settings: Settings) -> ReadinessService:
    """Build probes without running them or touching external resources."""

    return ReadinessService(
        probes=(
            PostgreSQLReadinessProbe(settings),
            ActiveModelReadinessProbe(settings),
        )
    )


def create_health_router(readiness: ReadinessService) -> APIRouter:
    """Create the two health routes without evaluating dependencies."""

    router = APIRouter(prefix="/health", tags=["health"])

    @router.get(
        "/live",
        operation_id="get_liveness",
        response_model=LivenessResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_liveness() -> LivenessResponse:
        return LivenessResponse()

    @router.get(
        "/ready",
        operation_id="get_readiness",
        response_model=ReadinessResponse,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ReadinessResponse,
                "description": "One or more required dependencies are unavailable.",
            }
        },
        status_code=status.HTTP_200_OK,
    )
    def get_readiness(response: Response) -> ReadinessResponse:
        result = readiness.evaluate()
        if result.status is ReadinessStatus.NOT_READY:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return result

    return router
