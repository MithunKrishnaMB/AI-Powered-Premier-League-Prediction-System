"""Loopback verification of the pinned production ASGI command boundary."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import cast

_WINDOWS_CTRL_BREAK_RETURN_CODE = 3


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _read_json(url: str) -> tuple[int, dict[str, object], dict[str, str]]:
    request = urllib.request.Request(url, headers={"X-Request-ID": "runtime-test"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return (
                response.status,
                json.loads(response.read()),
                dict(response.headers.items()),
            )
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers.items())


def _wait_for_liveness(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"production runtime exited early\nstdout={stdout}\nstderr={stderr}"
            )
        try:
            status, _, _ = _read_json(f"{base_url}/health/live")
        except OSError, ValueError:
            time.sleep(0.05)
            continue
        if status == 200:
            return
        time.sleep(0.05)
    raise AssertionError("production runtime did not become live")


def _stop_runtime(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
    try:
        return process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def test_production_uvicorn_runtime_is_live_and_dependency_fail_closed(
    tmp_path: Path,
) -> None:
    port = _unused_loopback_port()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.casefold().startswith("plp_")
    }
    environment.update(
        {
            "PLP_ENVIRONMENT": "production",
            "PLP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "PLP_REGISTRY_ROOT": str(tmp_path / "artifacts" / "registry"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "pl_platform.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-proxy-headers",
            "--timeout-graceful-shutdown",
            "30",
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creation_flags,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_liveness(base_url, process)
        live_status, live, live_headers = _read_json(f"{base_url}/health/live")
        ready_status, ready, ready_headers = _read_json(f"{base_url}/health/ready")
        openapi_status, openapi, _ = _read_json(f"{base_url}/openapi.json")

        assert live_status == openapi_status == 200
        assert live == {"schema_version": 1, "status": "alive"}
        assert ready_status == 503
        assert ready == {
            "schema_version": 1,
            "status": "not_ready",
            "dependencies": [
                {
                    "name": "postgresql",
                    "status": "not_ready",
                    "reason": "production_database_not_configured",
                },
                {
                    "name": "active_model",
                    "status": "not_ready",
                    "reason": "no_active_model",
                },
            ],
        }
        normalized_live_headers = {
            name.casefold(): value for name, value in live_headers.items()
        }
        normalized_ready_headers = {
            name.casefold(): value for name, value in ready_headers.items()
        }
        assert normalized_live_headers["strict-transport-security"] == (
            "max-age=31536000; includeSubDomains"
        )
        assert normalized_ready_headers["x-request-id"] == "runtime-test"
        paths = cast(Mapping[str, Mapping[str, object]], openapi["paths"])
        assert len(paths) == 16
        assert all(set(path_item) == {"get"} for path_item in paths.values())
        assert tuple(tmp_path.iterdir()) == ()
    finally:
        stdout, stderr = _stop_runtime(process)

    expected_return_codes = (
        {0, _WINDOWS_CTRL_BREAK_RETURN_CODE} if os.name == "nt" else {0}
    )
    assert process.returncode in expected_return_codes, (
        f"stdout={stdout}\nstderr={stderr}"
    )
