"""Shared synthetic current-provider contracts for unit tests."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from pl_platform.domain.current import (
    CurrentSeasonScope,
    ProviderCompetitionIdentifier,
    ProviderFixtureIdentifier,
    ProviderSeasonIdentifier,
)
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonEntryStatus,
    SeasonTeamMembership,
)
from pl_platform.domain.teams import (
    CanonicalTeam,
    TeamAlias,
    TeamRegistry,
    TeamRegistryDocument,
)
from pl_platform.ingestion.current import (
    CompletedResultsRequest,
    CurrentProviderCapability,
    CurrentProviderRequest,
    CurrentSeasonFixturesRequest,
    CurrentSeasonPlayersRequest,
    CurrentSeasonSquadsRequest,
    CurrentSeasonTeamsRequest,
    ExactProviderResponse,
    FixtureStatusRequest,
    PageMetadata,
    ProviderCompatibility,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    StandingsRequest,
    provider_request_identity,
)

SOURCE = "current-test-provider"
NOW = datetime(2026, 9, 14, 10, tzinfo=UTC)


def scope() -> CurrentSeasonScope:
    return CurrentSeasonScope(
        competition_id="eng-premier-league",
        season_id="2026-2027",
        provider_competition_id=ProviderCompetitionIdentifier(
            source_id=SOURCE,
            external_id="PL",
        ),
        provider_season_id=ProviderSeasonIdentifier(
            source_id=SOURCE,
            external_id="2026",
        ),
    )


def compatibility() -> ProviderCompatibility:
    return ProviderCompatibility(
        provider_api_version="api-v1",
        parser_schema_version="parser-v1",
    )


def request_for(capability: CurrentProviderCapability) -> CurrentProviderRequest:
    if capability is CurrentProviderCapability.TEAMS:
        return CurrentSeasonTeamsRequest(scope=scope(), compatibility=compatibility())
    if capability is CurrentProviderCapability.FIXTURES:
        return CurrentSeasonFixturesRequest(
            scope=scope(),
            compatibility=compatibility(),
        )
    if capability is CurrentProviderCapability.COMPLETED_RESULTS:
        return CompletedResultsRequest(scope=scope(), compatibility=compatibility())
    if capability is CurrentProviderCapability.FIXTURE_STATUS:
        return FixtureStatusRequest(
            scope=scope(),
            compatibility=compatibility(),
            fixture_ids=(
                ProviderFixtureIdentifier(source_id=SOURCE, external_id="fixture-1"),
            ),
        )
    if capability is CurrentProviderCapability.STANDINGS:
        return StandingsRequest(scope=scope(), compatibility=compatibility())
    if capability is CurrentProviderCapability.PLAYERS:
        return CurrentSeasonPlayersRequest(scope=scope(), compatibility=compatibility())
    if capability is CurrentProviderCapability.SQUADS:
        return CurrentSeasonSquadsRequest(
            scope=scope(),
            compatibility=compatibility(),
            as_of_date=date(2026, 9, 14),
        )
    raise ValueError("test helper supports team and fixture requests only")


def capture_for(
    capability: CurrentProviderCapability,
    item_count: int,
    *,
    retrieved_at: datetime = NOW,
    body: bytes = b'{"ok":true}\n',
) -> ProviderResponseCapture:
    request = request_for(capability)
    return ProviderResponseCapture(
        source_id=SOURCE,
        capability=capability,
        request_identity=provider_request_identity(request),
        retrieved_at=retrieved_at,
        provider_generated_at=retrieved_at - timedelta(seconds=1),
        compatibility=compatibility(),
        page=PageMetadata(returned_count=item_count, has_more=False),
        quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
        response=ExactProviderResponse(
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        ),
    )


def registry_and_season() -> tuple[TeamRegistry, PremierLeagueSeason]:
    teams: list[CanonicalTeam] = []
    memberships: list[SeasonTeamMembership] = []
    for ordinal in range(20):
        identity = uuid5(NAMESPACE_URL, f"current-test-team:{ordinal:02d}")
        teams.append(
            CanonicalTeam(
                id=identity,
                slug=f"team-{ordinal:02d}",
                name=f"Team {ordinal:02d}",
                country_code="ENG",
                aliases=(
                    TeamAlias(
                        source_id=SOURCE,
                        external_name=f"Provider Team {ordinal:02d}",
                        external_id=f"provider-{ordinal:02d}",
                    ),
                ),
            )
        )
        promoted = ordinal >= 17
        memberships.append(
            SeasonTeamMembership(
                team_id=identity,
                entry_status=(
                    SeasonEntryStatus.PROMOTED
                    if promoted
                    else SeasonEntryStatus.CONTINUED
                ),
                previous_competition_id=("eng-championship" if promoted else None),
            )
        )
    registry = TeamRegistry(TeamRegistryDocument(schema_version=2, teams=tuple(teams)))
    season = PremierLeagueSeason(
        id="2026-2027",
        competition_id="eng-premier-league",
        starts_on=date(2026, 8, 1),
        ends_on=date(2027, 5, 31),
        completed=False,
        memberships=tuple(memberships),
    )
    return registry, season
