"""Smoke tests for the installable project package."""

import pl_platform


def test_package_exposes_version() -> None:
    assert pl_platform.__version__ == "0.1.0"
