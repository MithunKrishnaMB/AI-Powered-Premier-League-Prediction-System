"""End-to-end PostgreSQL synchronization for reviewed current squads."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from pl_platform.core.config import Settings
from pl_platform.ingestion.current_squads import (
    assemble_current_squad_snapshot,
    transform_current_players,
    transform_current_squads,
)
from pl_platform.persistence.current_squads import CurrentSquadRepository
from pl_platform.persistence.database import create_database_engine
from pl_platform.persistence.provider_cache import ProviderCacheRepository
from pl_platform.persistence.repositories import (
    FilesystemRawManifestVerifier,
    PostgresAggregateRepository,
)
from tests.integration.persistence.test_current_sync import _seed_current_identity
from tests.unit.ingestion.current_squad_helpers import (
    player_registry,
    players_response,
    squads_response,
)
from tests.unit.ingestion.test_current_reconciliation import _resolution


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
    if revision != "f0010_step_10_5":
        engine.dispose()
        pytest.skip("test PostgreSQL database is not at the Step 6.8 head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_player_and_complete_squad_sync_is_exact_and_idempotent(
    test_engine: Engine,
) -> None:
    verifier = FilesystemRawManifestVerifier(
        manifest_path=Path("data/manifests/football-data.json"),
        data_root=Path("data"),
    )
    repository = PostgresAggregateRepository(test_engine, verifier)
    cache = ProviderCacheRepository(test_engine, verifier)
    _seed_current_identity(repository)
    team_resolution, season = _resolution()
    registry = player_registry()
    player_response = players_response()
    squad_response = squads_response()
    players = transform_current_players(player_response, registry, season)
    squads = transform_current_squads(
        squad_response,
        team_resolution,
        players,
        registry,
        season,
    )
    snapshot = assemble_current_squad_snapshot(squads, season)
    for capture in (player_response.capture, squad_response.capture):
        cache.store(capture, expires_at=capture.retrieved_at + timedelta(hours=1))
    current = CurrentSquadRepository(repository)

    player_first = current.synchronize_players(players)
    player_second = current.synchronize_players(players)
    squad_first = current.synchronize_squads(snapshot)
    squad_second = current.synchronize_squads(snapshot)

    assert player_first.inserted_rows + player_first.existing_rows == 60
    assert player_second.inserted_rows == 0
    assert squad_first.inserted_rows + squad_first.existing_rows == 82
    assert squad_second.inserted_rows == 0
    with test_engine.connect() as connection:
        player_count = connection.execute(
            text("SELECT count(*) FROM identity.player")
        ).scalar_one()
        member_count = connection.execute(
            text("SELECT count(*) FROM football.current_squad_member")
        ).scalar_one()
        team_count = connection.execute(
            text("SELECT count(*) FROM football.current_squad_snapshot_team")
        ).scalar_one()

    assert player_count == 20
    assert member_count == 20
    assert team_count == 20
