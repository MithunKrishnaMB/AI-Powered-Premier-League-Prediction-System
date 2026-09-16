"""Smoke tests for the installable project package."""

import pl_platform


def test_package_exposes_version() -> None:
    assert pl_platform.__version__ == "0.1.0"


def test_ingestion_keeps_live_boundaries_lazy_and_public() -> None:
    from pl_platform.ingestion import (
        CacheAwareFinalResultReconciler,
        CacheAwareLiveFixtureReader,
    )

    assert CacheAwareFinalResultReconciler.__name__ == (
        "CacheAwareFinalResultReconciler"
    )
    assert CacheAwareLiveFixtureReader.__name__ == "CacheAwareLiveFixtureReader"
