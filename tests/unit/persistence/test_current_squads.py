"""Current player and squad write-plan tests."""

import pytest

from pl_platform.ingestion.current_squads import (
    CanonicalSquadSnapshot,
    CurrentPlayerResolution,
    assemble_current_squad_snapshot,
    transform_current_players,
    transform_current_squads,
)
from pl_platform.persistence.current_squads import (
    current_players_sync_plan,
    current_squad_sync_plan,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    PersistenceTable,
    RepositoryContractError,
)
from tests.unit.ingestion.current_squad_helpers import (
    player_registry,
    players_response,
    squads_response,
)
from tests.unit.ingestion.test_current_reconciliation import _resolution


def _transformed() -> tuple[CurrentPlayerResolution, CanonicalSquadSnapshot]:
    team_resolution, season = _resolution()
    registry = player_registry()
    players = transform_current_players(players_response(), registry, season)
    squads = transform_current_squads(
        squads_response(), team_resolution, players, registry, season
    )
    return players, assemble_current_squad_snapshot(squads, season)


def test_player_plan_separates_canonical_and_provider_identities() -> None:
    players, _ = _transformed()

    plan = current_players_sync_plan(players)

    assert plan.kind is AggregateKind.CURRENT_PLAYERS
    assert sum(row.table is PersistenceTable.PLAYER for row in plan.rows) == 20
    assert (
        sum(
            row.table is PersistenceTable.CURRENT_PLAYER_SOURCE_REFERENCE
            for row in plan.rows
        )
        == 20
    )
    assert (
        sum(
            row.table is PersistenceTable.CURRENT_PLAYER_OBSERVATION
            for row in plan.rows
        )
        == 20
    )


def test_squad_plan_is_complete_ordered_and_content_derived() -> None:
    _, snapshot = _transformed()

    first = current_squad_sync_plan(snapshot)
    second = current_squad_sync_plan(snapshot)

    assert first == second
    assert first.kind is AggregateKind.CURRENT_SQUADS
    assert len(first.objects) == 1
    assert (
        sum(
            row.table is PersistenceTable.CURRENT_SQUAD_SNAPSHOT_TEAM
            for row in first.rows
        )
        == 20
    )
    assert (
        sum(row.table is PersistenceTable.CURRENT_SQUAD_MEMBER for row in first.rows)
        == 20
    )


def test_empty_player_sync_fails_before_database() -> None:
    players, _ = _transformed()
    empty = players.__class__(
        source_id=players.source_id,
        competition_id=players.competition_id,
        season_id=players.season_id,
        players=(),
    )
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        current_players_sync_plan(empty)
