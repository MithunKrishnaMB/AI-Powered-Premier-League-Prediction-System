"""Project-wide pytest options for explicit local release verification."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the opt-in gate that requires all local release evidence."""

    parser.getgroup("local release").addoption(
        "--require-local-release",
        action="store_true",
        default=False,
        help=(
            "require isolated local PostgreSQL, raw-manifest, registry and "
            "migration-cycle checks instead of skipping them"
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Keep destructive-looking release checks explicit for portable test runs."""

    if bool(config.getoption("--require-local-release")):
        return
    skip = pytest.mark.skip(reason="requires --require-local-release")
    for item in items:
        if "local_release" in item.keywords:
            item.add_marker(skip)
