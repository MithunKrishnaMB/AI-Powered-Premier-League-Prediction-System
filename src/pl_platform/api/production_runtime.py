"""Validated production entry point for the containerized API process."""

from __future__ import annotations

import os
from typing import NoReturn


def _port() -> str:
    raw_port = os.environ.get("PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit("PORT must be an integer from 1 through 65535") from exc
    if not 1 <= port <= 65_535:
        raise SystemExit("PORT must be an integer from 1 through 65535")
    return str(port)


def _uvicorn_command() -> tuple[str, ...]:
    return (
        "uvicorn",
        "pl_platform.api:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        _port(),
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
    command = _uvicorn_command()
    os.execvp(command[0], command)


if __name__ == "__main__":  # pragma: no cover - exercised by the built image
    main()
