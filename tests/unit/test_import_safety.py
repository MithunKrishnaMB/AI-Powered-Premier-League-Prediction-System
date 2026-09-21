"""Package-wide import-safety verification."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_every_package_module_imports_without_runtime_side_effects(
    tmp_path: Path,
) -> None:
    script = r"""
import importlib
import pkgutil
import socket
import sqlalchemy
import urllib.request

import pl_platform

def fail(*args, **kwargs):
    raise AssertionError("module import attempted external runtime work")

sqlalchemy.create_engine = fail
socket.create_connection = fail
urllib.request.urlopen = fail

module_names = sorted(
    item.name for item in pkgutil.walk_packages(
        pl_platform.__path__, prefix="pl_platform."
    )
)
for module_name in module_names:
    importlib.import_module(module_name)

print(len(module_names))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.casefold().startswith("plp_")
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip()) >= 50
    assert tuple(tmp_path.iterdir()) == ()
