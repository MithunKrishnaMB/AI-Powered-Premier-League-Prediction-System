"""Tests for the fail-closed production process entry point."""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest

from pl_platform.api import production_runtime


class RuntimeReplaced(Exception):
    """Sentinel raised instead of replacing the unit-test process."""


def test_production_runtime_rejects_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLP_ENVIRONMENT", "development")

    with pytest.raises(SystemExit, match="must be 'production'"):
        production_runtime.main()


def test_production_runtime_executes_the_pinned_single_worker_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[tuple[str, tuple[str, ...]]] = []

    def replace_process(executable: str, arguments: Sequence[str]) -> None:
        executed.append((executable, tuple(arguments)))
        raise RuntimeReplaced

    monkeypatch.setenv("PLP_ENVIRONMENT", "production")
    monkeypatch.setattr(os, "execvp", replace_process)

    with pytest.raises(RuntimeReplaced):
        production_runtime.main()

    assert executed == [
        (
            "uvicorn",
            (
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
            ),
        )
    ]
