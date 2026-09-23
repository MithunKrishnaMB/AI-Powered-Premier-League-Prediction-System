"""Read-only local release evidence that must not be silently skipped."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from pl_platform.core.config import Settings
from pl_platform.ingestion.manifest import load_manifest
from pl_platform.persistence.database import (
    check_database_connection,
    create_database_engine,
)
from pl_platform.persistence.repositories import FilesystemRawManifestVerifier
from pl_platform.registry.active_model import FilesystemRegistryHistorySource

MIGRATION_HEAD = "f0010_step_10_5"


def _revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one_or_none()


@pytest.mark.local_release
@pytest.mark.postgresql
def test_required_local_release_evidence_is_complete_and_read_only() -> None:
    settings = Settings()
    assert settings.database_url is not None, "development PostgreSQL is required"
    assert settings.test_database_url is not None, "test PostgreSQL is required"

    development = create_database_engine(settings, target="development")
    test = create_database_engine(settings, target="test")
    try:
        development_info = check_database_connection(
            development,
            target="development",
        )
        test_info = check_database_connection(test, target="test")
        assert development_info.database_name == "pl_platform_dev"
        assert test_info.database_name == "pl_platform_test"
        assert development_info.database_name != test_info.database_name
        assert development_info.database_user == test_info.database_user == "pl_app"
        assert _revision(development) == _revision(test) == MIGRATION_HEAD
    finally:
        development.dispose()
        test.dispose()

    manifest_path = Path("data/manifests/football-data.json")
    manifest = load_manifest(manifest_path)
    evidence = FilesystemRawManifestVerifier(manifest_path, Path("data")).verify()
    expected_artifacts = tuple(entry.id for entry in manifest.files)
    assert len(expected_artifacts) == 11
    assert evidence.verified_artifact_ids == expected_artifacts

    registry = FilesystemRegistryHistorySource().load_entries(settings.registry_root)
    assert len(registry) == 1
    assert registry[0].state == "development_accepted"
    assert registry[0].event_count == 2
    assert not any(entry.state == "active" for entry in registry)
