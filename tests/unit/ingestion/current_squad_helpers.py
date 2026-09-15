"""Synthetic reviewed player and complete squad fixtures."""

from datetime import date
from uuid import NAMESPACE_URL, uuid5

from pl_platform.domain.current import (
    CurrentSeasonPlayer,
    CurrentSeasonSquad,
    CurrentSquadMembership,
    ProviderPlayerIdentifier,
    ProviderSquadIdentifier,
    ProviderTeamIdentifier,
    SquadMembershipKind,
)
from pl_platform.domain.players import (
    CanonicalPlayer,
    PlayerAlias,
    PlayerRegistry,
    PlayerRegistryDocument,
)
from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentSeasonPlayersResponse,
    CurrentSeasonSquadsResponse,
)
from tests.unit.ingestion.current_helpers import SOURCE, capture_for, scope


def player_registry() -> PlayerRegistry:
    players = tuple(
        CanonicalPlayer(
            id=uuid5(NAMESPACE_URL, f"current-test-player:{ordinal:02d}"),
            slug=f"player-{ordinal:02d}",
            display_name=f"Player {ordinal:02d}",
            aliases=(
                PlayerAlias(
                    source_id=SOURCE,
                    external_name=f"Provider Player {ordinal:02d}",
                    external_id=f"player-{ordinal:02d}",
                ),
            ),
        )
        for ordinal in range(20)
    )
    return PlayerRegistry(PlayerRegistryDocument(schema_version=1, players=players))


def players_response() -> CurrentSeasonPlayersResponse:
    items = tuple(
        CurrentSeasonPlayer(
            provider_player_id=ProviderPlayerIdentifier(
                source_id=SOURCE, external_id=f"player-{ordinal:02d}"
            ),
            provider_name=f"Provider Player {ordinal:02d}",
            date_of_birth=date(2000, 1, 1),
            nationality_code="ENG",
            provider_position="midfield",
        )
        for ordinal in range(20)
    )
    return CurrentSeasonPlayersResponse(
        scope=scope(),
        items=items,
        capture=capture_for(CurrentProviderCapability.PLAYERS, 20),
    )


def squads_response() -> CurrentSeasonSquadsResponse:
    items = tuple(
        CurrentSeasonSquad(
            provider_squad_id=ProviderSquadIdentifier(
                source_id=SOURCE, external_id=f"squad-{ordinal:02d}"
            ),
            provider_team_id=ProviderTeamIdentifier(
                source_id=SOURCE, external_id=f"provider-{ordinal:02d}"
            ),
            as_of_date=date(2026, 9, 14),
            memberships=(
                CurrentSquadMembership(
                    provider_player_id=ProviderPlayerIdentifier(
                        source_id=SOURCE, external_id=f"player-{ordinal:02d}"
                    ),
                    provider_player_name=f"Provider Player {ordinal:02d}",
                    kind=SquadMembershipKind.PERMANENT,
                    effective_from=date(2026, 7, 1),
                    registered_from=date(2026, 8, 1),
                    shirt_number=ordinal + 1,
                ),
            ),
        )
        for ordinal in range(20)
    )
    return CurrentSeasonSquadsResponse(
        scope=scope(),
        items=items,
        capture=capture_for(CurrentProviderCapability.SQUADS, 20),
    )
