"""End-to-end PostgreSQL synchronization for current-season match state."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from pl_platform.core.config import Settings
from pl_platform.ingestion.current_transform import (
    transform_completed_results,
    transform_current_fixtures,
    transform_current_standings,
)
from pl_platform.persistence.current_sync import CurrentSeasonRepository
from pl_platform.persistence.database import create_database_engine
from pl_platform.persistence.provider_cache import ProviderCacheRepository
from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    FilesystemRawManifestVerifier,
    ImmutableRow,
    PersistenceTable,
    PostgresAggregateRepository,
    StoredObject,
)
from tests.unit.ingestion.test_current_reconciliation import (
    _resolution,
    _result_response,
    _standings_response,
)
from tests.unit.ingestion.test_current_transform import _fixture, _fixture_response


@pytest.fixture(scope="module")
def test_engine() -> Iterator[Engine]:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.skip("test PostgreSQL URL is not configured")
    engine = create_database_engine(settings, target="test")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if revision != "f0008_step_7_7":
        engine.dispose()
        pytest.skip("test PostgreSQL database is not at the Step 6.8 head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def repositories(
    test_engine: Engine,
) -> tuple[PostgresAggregateRepository, ProviderCacheRepository]:
    verifier = FilesystemRawManifestVerifier(
        manifest_path=Path("data/manifests/football-data.json"),
        data_root=Path("data"),
    )
    return (
        PostgresAggregateRepository(test_engine, verifier),
        ProviderCacheRepository(test_engine, verifier),
    )


def _seed_current_identity(repository: PostgresAggregateRepository) -> None:
    resolution, season = _resolution()
    season_document = StoredObject.from_bytes(
        b'{"current_test_season_registry":1}',
        media_type="application/json",
        encoding="utf-8",
        format_id="current-test-season-registry-v1",
        canonicalization_profile=CanonicalizationProfile.IDENTITY_JSON,
    )
    rows = [
        ImmutableRow.build(
            PersistenceTable.COMPETITION,
            {
                "competition_id": season.competition_id,
                "display_name": "English Premier League",
                "country_code": "ENG",
                "timezone_name": "Europe/London",
            },
            identity_columns=("competition_id",),
        ),
        ImmutableRow.build(
            PersistenceTable.SOURCE,
            {
                "source_id": resolution.source_id,
                "provider_name": "Synthetic Current Test Provider",
                "homepage_url": "https://current.example.test",
                "attribution": "Synthetic integration test data",
                "usage_notice": "Tests only",
            },
            identity_columns=("source_id",),
        ),
        ImmutableRow.build(
            PersistenceTable.REFERENCE_DOCUMENT,
            {
                "document_sha256": season_document.sha256,
                "document_kind": "season_registry",
                "schema_version": 1,
            },
            identity_columns=("document_sha256",),
        ),
    ]
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.TEAM,
            {"team_id": membership.team_id},
            identity_columns=("team_id",),
        )
        for membership in season.memberships
    )
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SEASON,
            {
                "competition_id": season.competition_id,
                "season_id": season.id,
            },
            identity_columns=("competition_id", "season_id"),
        )
    )
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SEASON_REGISTRY_ENTRY,
            {
                "season_registry_sha256": season_document.sha256,
                "competition_id": season.competition_id,
                "season_id": season.id,
                "ordinal": 0,
                "starts_on": season.starts_on,
                "ends_on": season.ends_on,
                "completed": season.completed,
            },
            identity_columns=(
                "season_registry_sha256",
                "competition_id",
                "season_id",
            ),
        )
    )
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.SEASON_MEMBERSHIP,
            {
                "season_registry_sha256": season_document.sha256,
                "competition_id": season.competition_id,
                "season_id": season.id,
                "team_id": membership.team_id,
                "ordinal": ordinal,
                "entry_status": membership.entry_status.value,
                "previous_competition_id": membership.previous_competition_id,
            },
            identity_columns=(
                "season_registry_sha256",
                "competition_id",
                "season_id",
                "team_id",
            ),
        )
        for ordinal, membership in enumerate(season.memberships)
    )
    repository.persist(
        AggregateWritePlan(
            kind=AggregateKind.IDENTITY_REFERENCE,
            identity="current-sync-test-identity",
            objects=(season_document,),
            rows=tuple(rows),
        )
    )


@pytest.mark.postgresql
def test_fixture_result_and_standings_sync_is_exact_and_idempotent(
    repositories: tuple[PostgresAggregateRepository, ProviderCacheRepository],
    test_engine: Engine,
) -> None:
    repository, cache = repositories
    _seed_current_identity(repository)
    resolution, season = _resolution()
    fixture_response = _fixture_response(
        (
            _fixture(
                "fixture-1",
                0,
                1,
                datetime(2026, 9, 10, 12, tzinfo=UTC),
            ),
        )
    )
    fixtures = transform_current_fixtures(fixture_response, resolution, season)
    result_response = _result_response()
    results = transform_completed_results(result_response, resolution, season)
    standings_response = _standings_response()
    standings = transform_current_standings(standings_response, resolution, season)
    for capture in (
        fixture_response.capture,
        result_response.capture,
        standings_response.capture,
    ):
        cache.store(capture, expires_at=capture.retrieved_at + timedelta(hours=1))
    current = CurrentSeasonRepository(repository)

    fixture_first = current.synchronize_fixtures(fixtures)
    fixture_second = current.synchronize_fixtures(fixtures)
    result_first = current.reconcile_results(results)
    result_second = current.reconcile_results(results)
    standing_first = current.synchronize_standings(standings, results)
    standing_second = current.synchronize_standings(standings, results)

    assert fixture_first.inserted_rows + fixture_first.existing_rows == 7
    assert fixture_second.inserted_rows == 0
    assert result_first.inserted_rows + result_first.existing_rows == 4
    assert result_second.inserted_rows == 0
    assert standing_first.inserted_rows + standing_first.existing_rows == 41
    assert standing_second.inserted_rows == 0
    with test_engine.connect() as connection:
        score = connection.execute(
            text(
                "SELECT full_time_home_goals, full_time_away_goals "
                "FROM football.current_completed_result"
            )
        ).one()
        standing_count = connection.execute(
            text("SELECT count(*) FROM football.current_standing_row")
        ).scalar_one()
    assert score == (2, 1)
    assert standing_count == 20
