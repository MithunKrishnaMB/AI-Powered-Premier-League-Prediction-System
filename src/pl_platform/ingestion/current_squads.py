"""Provider-neutral current player and squad transformation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from uuid import NAMESPACE_URL, UUID, uuid5

from pl_platform.domain.current import (
    CurrentSeasonPlayer,
    CurrentSeasonSquad,
    ProviderPlayerIdentifier,
)
from pl_platform.domain.players import CanonicalPlayer, PlayerRegistry
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.ingestion.current import (
    CurrentSeasonPlayersResponse,
    CurrentSeasonSquadsResponse,
    ProviderResponseCapture,
)
from pl_platform.ingestion.current_transform import CurrentTeamResolution


class CurrentSquadTransformationError(ValueError):
    """Player or squad data violates reviewed identity or chronology."""


@dataclass(frozen=True, slots=True)
class ResolvedCurrentSeasonPlayer:
    observation: CurrentSeasonPlayer
    canonical_player: CanonicalPlayer
    capture: ProviderResponseCapture


@dataclass(frozen=True, slots=True)
class CurrentPlayerResolution:
    source_id: str
    competition_id: str
    season_id: str
    players: tuple[ResolvedCurrentSeasonPlayer, ...]

    @property
    def by_provider_id(self) -> Mapping[str, CanonicalPlayer]:
        return MappingProxyType(
            {
                item.observation.provider_player_id.external_id: (item.canonical_player)
                for item in self.players
            }
        )


@dataclass(frozen=True, slots=True)
class CanonicalSquadMembership:
    player_id: UUID
    loan_parent_team_id: UUID | None
    provider_player_id: ProviderPlayerIdentifier
    provider_player_name: str
    kind: str
    effective_from: date
    effective_to: date | None
    registered_from: date
    registered_to: date | None
    shirt_number: int | None


@dataclass(frozen=True, slots=True)
class CanonicalCurrentSquad:
    squad_id: UUID
    team_id: UUID
    observation: CurrentSeasonSquad
    memberships: tuple[CanonicalSquadMembership, ...]
    competition_id: str
    season_id: str
    capture: ProviderResponseCapture


@dataclass(frozen=True, slots=True)
class CanonicalSquadSnapshot:
    competition_id: str
    season_id: str
    source_id: str
    as_of_date: date
    squads: tuple[CanonicalCurrentSquad, ...]


def canonical_squad_id(competition_id: str, season_id: str, team_id: UUID) -> UUID:
    """Derive a provider-independent season/team squad identity."""

    return uuid5(
        NAMESPACE_URL,
        f"pl-platform:squad:{competition_id}|{season_id}|{team_id}",
    )


def _validate_scope(
    competition_id: str,
    season_id: str,
    season: PremierLeagueSeason,
) -> None:
    if competition_id != season.competition_id or season_id != season.id:
        raise CurrentSquadTransformationError(
            "provider scope does not match the reviewed canonical season"
        )


def transform_current_players(
    response: CurrentSeasonPlayersResponse,
    registry: PlayerRegistry,
    season: PremierLeagueSeason,
) -> CurrentPlayerResolution:
    """Resolve current players with reviewed exact evidence only."""

    _validate_scope(response.scope.competition_id, response.scope.season_id, season)
    resolved: list[ResolvedCurrentSeasonPlayer] = []
    for observation in response.items:
        player = registry.resolve_provider_player(
            observation.provider_player_id.source_id,
            observation.provider_player_id.external_id,
            observation.provider_name,
        )
        resolved.append(
            ResolvedCurrentSeasonPlayer(
                observation=observation,
                canonical_player=player,
                capture=response.capture,
            )
        )
    resolved.sort(key=lambda item: item.observation.provider_player_id.external_id)
    canonical_ids = tuple(item.canonical_player.id for item in resolved)
    if len(canonical_ids) != len(set(canonical_ids)):
        raise CurrentSquadTransformationError(
            "provider players resolve to duplicate canonical identities"
        )
    return CurrentPlayerResolution(
        source_id=response.scope.source_id,
        competition_id=response.scope.competition_id,
        season_id=response.scope.season_id,
        players=tuple(resolved),
    )


def transform_current_squads(
    response: CurrentSeasonSquadsResponse,
    team_resolution: CurrentTeamResolution,
    player_resolution: CurrentPlayerResolution,
    player_registry: PlayerRegistry,
    season: PremierLeagueSeason,
) -> tuple[CanonicalCurrentSquad, ...]:
    """Resolve squad membership, transfers and loans without inferred identity."""

    _validate_scope(response.scope.competition_id, response.scope.season_id, season)
    expected_scope = (
        response.scope.source_id,
        response.scope.competition_id,
        response.scope.season_id,
    )
    if (
        team_resolution.source_id,
        team_resolution.competition_id,
        team_resolution.season_id,
    ) != expected_scope or (
        player_resolution.source_id,
        player_resolution.competition_id,
        player_resolution.season_id,
    ) != expected_scope:
        raise CurrentSquadTransformationError(
            "team or player resolution does not match squad scope"
        )
    teams = team_resolution.by_provider_id
    players = player_resolution.by_provider_id
    transformed: list[CanonicalCurrentSquad] = []
    for squad in response.items:
        if not season.starts_on <= squad.as_of_date <= season.ends_on:
            raise CurrentSquadTransformationError(
                "squad as-of date is outside the reviewed season"
            )
        try:
            team = teams[squad.provider_team_id.external_id]
        except KeyError as exc:
            raise CurrentSquadTransformationError(
                "squad references an unresolved provider team"
            ) from exc
        memberships: list[CanonicalSquadMembership] = []
        for membership in squad.memberships:
            try:
                player = players[membership.provider_player_id.external_id]
            except KeyError as exc:
                raise CurrentSquadTransformationError(
                    "squad references an unresolved provider player"
                ) from exc
            reviewed = player_registry.resolve_provider_player(
                membership.provider_player_id.source_id,
                membership.provider_player_id.external_id,
                membership.provider_player_name,
            )
            if reviewed.id != player.id:
                raise CurrentSquadTransformationError(
                    "squad player evidence conflicts with player resolution"
                )
            loan_parent_id: UUID | None = None
            if membership.loan_parent_provider_team_id is not None:
                try:
                    loan_parent_id = teams[
                        membership.loan_parent_provider_team_id.external_id
                    ].id
                except KeyError as exc:
                    raise CurrentSquadTransformationError(
                        "loan parent is an unresolved provider team"
                    ) from exc
                if loan_parent_id == team.id:
                    raise CurrentSquadTransformationError(
                        "loan parent and registered team must differ"
                    )
            if membership.registered_from < season.starts_on or (
                membership.registered_to is not None
                and membership.registered_to > season.ends_on
            ):
                raise CurrentSquadTransformationError(
                    "registration window is outside the reviewed season"
                )
            memberships.append(
                CanonicalSquadMembership(
                    player_id=player.id,
                    loan_parent_team_id=loan_parent_id,
                    provider_player_id=membership.provider_player_id,
                    provider_player_name=membership.provider_player_name,
                    kind=membership.kind.value,
                    effective_from=membership.effective_from,
                    effective_to=membership.effective_to,
                    registered_from=membership.registered_from,
                    registered_to=membership.registered_to,
                    shirt_number=membership.shirt_number,
                )
            )
        transformed.append(
            CanonicalCurrentSquad(
                squad_id=canonical_squad_id(
                    response.scope.competition_id,
                    response.scope.season_id,
                    team.id,
                ),
                team_id=team.id,
                observation=squad,
                memberships=tuple(memberships),
                competition_id=response.scope.competition_id,
                season_id=response.scope.season_id,
                capture=response.capture,
            )
        )
    return tuple(sorted(transformed, key=lambda item: item.team_id))


def assemble_current_squad_snapshot(
    squads: Sequence[CanonicalCurrentSquad],
    season: PremierLeagueSeason,
) -> CanonicalSquadSnapshot:
    """Require one complete, simultaneous 20-team squad view before persistence."""

    if not squads:
        raise CurrentSquadTransformationError("squad snapshot cannot be empty")
    scopes = {
        (item.capture.source_id, item.competition_id, item.season_id) for item in squads
    }
    as_of_dates = {item.observation.as_of_date for item in squads}
    team_ids = tuple(item.team_id for item in squads)
    if len(scopes) != 1 or len(as_of_dates) != 1:
        raise CurrentSquadTransformationError(
            "squad snapshot must use one source, scope and as-of date"
        )
    if len(team_ids) != len(set(team_ids)) or set(team_ids) != set(season.team_ids):
        raise CurrentSquadTransformationError(
            "squad snapshot must contain every reviewed season team exactly once"
        )
    player_ids = tuple(
        membership.player_id for squad in squads for membership in squad.memberships
    )
    if len(player_ids) != len(set(player_ids)):
        raise CurrentSquadTransformationError(
            "a player cannot have multiple active squad registrations in one snapshot"
        )
    source_id, competition_id, season_id = next(iter(scopes))
    _validate_scope(competition_id, season_id, season)
    return CanonicalSquadSnapshot(
        competition_id=competition_id,
        season_id=season_id,
        source_id=source_id,
        as_of_date=next(iter(as_of_dates)),
        squads=tuple(sorted(squads, key=lambda item: item.team_id)),
    )
