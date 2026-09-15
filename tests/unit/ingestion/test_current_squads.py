"""Current player and squad transformation tests."""

import pytest

from pl_platform.domain.current import ProviderTeamIdentifier, SquadMembershipKind
from pl_platform.ingestion.current_squads import (
    CurrentSquadTransformationError,
    assemble_current_squad_snapshot,
    canonical_squad_id,
    transform_current_players,
    transform_current_squads,
)
from tests.unit.ingestion.current_helpers import SOURCE
from tests.unit.ingestion.current_squad_helpers import (
    player_registry,
    players_response,
    squads_response,
)
from tests.unit.ingestion.test_current_reconciliation import _resolution


def test_players_and_complete_squad_snapshot_resolve_exact_identities() -> None:
    team_resolution, season = _resolution()
    registry = player_registry()
    players = transform_current_players(players_response(), registry, season)
    squads = transform_current_squads(
        squads_response(), team_resolution, players, registry, season
    )

    snapshot = assemble_current_squad_snapshot(squads, season)

    assert len(snapshot.squads) == 20
    assert snapshot.squads[0].squad_id == canonical_squad_id(
        season.competition_id,
        season.id,
        snapshot.squads[0].team_id,
    )
    assert snapshot.squads[0].memberships[0].player_id in {
        item.canonical_player.id for item in players.players
    }


def test_squad_snapshot_rejects_incomplete_or_unknown_membership() -> None:
    team_resolution, season = _resolution()
    registry = player_registry()
    players = transform_current_players(players_response(), registry, season)
    squads = transform_current_squads(
        squads_response(), team_resolution, players, registry, season
    )
    with pytest.raises(CurrentSquadTransformationError, match="every reviewed"):
        assemble_current_squad_snapshot(squads[:-1], season)

    bad_squad = squads_response().items[0]
    bad_membership = bad_squad.memberships[0].model_copy(
        update={
            "provider_player_id": bad_squad.memberships[
                0
            ].provider_player_id.model_copy(update={"external_id": "unknown-player"})
        }
    )
    bad_response = squads_response().model_copy(
        update={
            "items": (
                bad_squad.model_copy(update={"memberships": (bad_membership,)}),
                *squads_response().items[1:],
            )
        }
    )
    with pytest.raises(CurrentSquadTransformationError, match="unresolved"):
        transform_current_squads(
            bad_response, team_resolution, players, registry, season
        )


def test_loan_membership_resolves_exact_distinct_parent_team() -> None:
    team_resolution, season = _resolution()
    registry = player_registry()
    players = transform_current_players(players_response(), registry, season)
    response = squads_response()
    first = response.items[0]
    loan = first.memberships[0].model_copy(
        update={
            "kind": SquadMembershipKind.LOAN,
            "loan_parent_provider_team_id": ProviderTeamIdentifier(
                source_id=SOURCE,
                external_id="provider-01",
            ),
        }
    )
    changed = response.model_copy(
        update={
            "items": (
                first.model_copy(update={"memberships": (loan,)}),
                *response.items[1:],
            )
        }
    )

    squads = transform_current_squads(
        changed,
        team_resolution,
        players,
        registry,
        season,
    )

    loan_membership = next(
        membership
        for squad in squads
        for membership in squad.memberships
        if membership.kind == SquadMembershipKind.LOAN.value
    )
    assert loan_membership.loan_parent_team_id is not None
