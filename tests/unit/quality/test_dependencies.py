"""Deterministic checks for the pinned local Python environment."""

from __future__ import annotations

import importlib.metadata
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

PIN_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[A-Za-z0-9._,-]+\])?==(?P<version>[^;\s]+)$"
)


def _declared_dependencies() -> tuple[str, ...]:
    document = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]
    dependency_groups = document["dependency-groups"]
    runtime = project["dependencies"]
    development = dependency_groups["dev"]
    assert isinstance(runtime, list)
    assert isinstance(development, list)
    return tuple(str(item) for item in (*runtime, *development))


def test_release_runtime_is_64_bit_python_3_14_7() -> None:
    assert sys.version_info[:3] == (3, 14, 7)
    assert struct.calcsize("P") * 8 == 64


def test_direct_runtime_and_development_dependencies_are_exact_and_installed() -> None:
    pins: dict[str, str] = {}
    for requirement in _declared_dependencies():
        match = PIN_PATTERN.fullmatch(requirement)
        assert match is not None, f"dependency is not exactly pinned: {requirement}"
        distribution = match.group("name")
        normalized = distribution.casefold().replace("_", "-")
        assert normalized not in pins, f"duplicate direct dependency: {distribution}"
        pins[normalized] = match.group("version")

    installed = {
        distribution: importlib.metadata.version(distribution)
        for distribution in sorted(pins)
    }

    assert installed == pins


def test_installed_environment_has_no_broken_requirements() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
