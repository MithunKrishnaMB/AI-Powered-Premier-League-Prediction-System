"""Validated production entry point for the containerized API process."""

from __future__ import annotations

import os
from typing import NoReturn

_UVICORN_COMMAND = (
    "uvicorn",
    "pl_platform.api:create_app",
    "--factory",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--workers",
    "1",
    "--no-proxy-headers",
    "--timeout-graceful-shutdown",
    "30",
    "--no-access-log",
)


def main() -> NoReturn:
    """Reject non-production configuration, then replace this process with Uvicorn."""

    if os.environ.get("PLP_ENVIRONMENT") != "production":
        raise SystemExit("PLP_ENVIRONMENT must be 'production' in the container")
    os.execvp(_UVICORN_COMMAND[0], _UVICORN_COMMAND)


if __name__ == "__main__":  # pragma: no cover - exercised by the built image
    main()
