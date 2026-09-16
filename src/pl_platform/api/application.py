"""Explicit FastAPI application factory with no import-time construction."""

from __future__ import annotations

from fastapi import FastAPI

from pl_platform import __version__
from pl_platform.api.errors import install_error_boundary
from pl_platform.api.health import (
    ReadinessService,
    create_health_router,
    default_readiness_service,
)
from pl_platform.core.config import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    readiness: ReadinessService | None = None,
) -> FastAPI:
    """Create one application without connecting or loading runtime artifacts."""

    resolved_settings = settings if settings is not None else get_settings()
    resolved_readiness = (
        readiness
        if readiness is not None
        else default_readiness_service(resolved_settings)
    )
    app = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        debug=resolved_settings.debug,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_error_boundary(app)
    app.include_router(create_health_router(resolved_readiness))
    return app
