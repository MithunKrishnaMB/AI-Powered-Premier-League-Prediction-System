"""Pure provider-neutral transformations for current-season observations."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from pl_platform.domain.current import (
    CurrentSeasonFixture,
    CurrentSeasonScope,
    CurrentSeasonTeam,
    ProviderTeamIdentifier,
)
from pl_platform.domain.fixtures import (
    Fixture,
    FixtureStatus,
    KickoffPrecision,
    SourceFixtureReference,
    canonical_fixture_id,
)
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.domain.teams import CanonicalTeam, TeamRegistry
from pl_platform.ingestion.current import (
    CurrentSeasonFixturesResponse,
    CurrentSeasonTeamsResponse,
    ProviderResponseCapture,
)


class CurrentTransformationError(ValueError):
    """Current observations cannot be mapped without violating a boundary."""


@dataclass(frozen=True, slots=True)
class ResolvedCurrentSeasonTeam:
    observation: CurrentSeasonTeam
    canonical_team: CanonicalTeam
    capture: ProviderResponseCapture

    @property
    def provider_id(self) -> ProviderTeamIdentifier:
        return self.observation.provider_team_id

    @property
    def provider_name(self) -> str:
        return self.observation.provider_name


@dataclass(frozen=True, slots=True)
class CurrentTeamResolution:
    source_id: str
    competition_id: str
    season_id: str
    teams: tuple[ResolvedCurrentSeasonTeam, ...]

    def __post_init__(self) -> None:
        provider_ids = tuple(item.provider_id.external_id for item in self.teams)
        canonical_ids = tuple(item.canonical_team.id for item in self.teams)
        if provider_ids != tuple(sorted(set(provider_ids))):
            raise CurrentTransformationError(
                "resolved provider teams must be unique and ordered"
            )
        if len(canonical_ids) != len(set(canonical_ids)):
            raise CurrentTransformationError(
                "provider observations resolve to duplicate canonical teams"
            )
        if any(item.provider_id.source_id != self.source_id for item in self.teams):
            raise CurrentTransformationError("resolved team source does not match")

    @property
    def by_provider_id(self) -> Mapping[str, CanonicalTeam]:
        return MappingProxyType(
            {item.provider_id.external_id: item.canonical_team for item in self.teams}
        )


@dataclass(frozen=True, slots=True)
class CanonicalCurrentFixture:
    fixture: Fixture
    observation: CurrentSeasonFixture
    capture: ProviderResponseCapture

    @property
    def source_timezone(self) -> str:
        return self.observation.kickoff.source_timezone

    @property
    def source_local_date(self) -> date:
        return self.observation.kickoff.source_local_date

    @property
    def provider_updated_at(self) -> datetime | None:
        return self.observation.provider_updated_at


@dataclass(frozen=True, slots=True)
class CurrentFixtureBatch:
    feature_cutoff_at: datetime
    knowledge_available_at: datetime
    source_timezone: str
    source_local_date: date
    fixtures: tuple[CanonicalCurrentFixture, ...]
    is_date_only_batch: bool


def _validate_scope(
    scope: CurrentSeasonScope,
    season: PremierLeagueSeason,
) -> None:
    if scope.competition_id != season.competition_id or scope.season_id != season.id:
        raise CurrentTransformationError(
            "current-provider scope does not match the reviewed canonical season"
        )


def transform_current_teams(
    response: CurrentSeasonTeamsResponse,
    registry: TeamRegistry,
    season: PremierLeagueSeason,
) -> CurrentTeamResolution:
    """Resolve provider teams using reviewed exact evidence only."""

    _validate_scope(response.scope, season)
    resolved: list[ResolvedCurrentSeasonTeam] = []
    for observation in response.items:
        team = registry.resolve_provider_team(
            observation.provider_team_id.source_id,
            observation.provider_team_id.external_id,
            observation.provider_name,
        )
        if team.id not in season.team_ids:
            raise CurrentTransformationError(
                "resolved provider team is not a member of the requested season"
            )
        resolved.append(
            ResolvedCurrentSeasonTeam(
                observation=observation,
                canonical_team=team,
                capture=response.capture,
            )
        )
    resolved.sort(key=lambda item: item.provider_id.external_id)
    return CurrentTeamResolution(
        source_id=response.scope.source_id,
        competition_id=response.scope.competition_id,
        season_id=response.scope.season_id,
        teams=tuple(resolved),
    )


def transform_current_fixtures(
    response: CurrentSeasonFixturesResponse,
    resolution: CurrentTeamResolution,
    season: PremierLeagueSeason,
) -> tuple[CanonicalCurrentFixture, ...]:
    """Map score-free current fixtures while retaining complete capture evidence."""

    _validate_scope(response.scope, season)
    if (
        resolution.source_id != response.scope.source_id
        or resolution.competition_id != response.scope.competition_id
        or resolution.season_id != response.scope.season_id
    ):
        raise CurrentTransformationError(
            "team resolution does not match the fixture response scope"
        )
    resolved = resolution.by_provider_id
    transformed: list[CanonicalCurrentFixture] = []
    for observation in response.items:
        if not (
            season.starts_on <= observation.kickoff.source_local_date <= season.ends_on
        ):
            raise CurrentTransformationError(
                "fixture source-local date is outside the requested season"
            )
        if observation.status is FixtureStatus.FINISHED:
            raise CurrentTransformationError(
                "finished fixtures require later completed-result reconciliation"
            )
        try:
            home = resolved[observation.home_provider_team_id.external_id]
            away = resolved[observation.away_provider_team_id.external_id]
        except KeyError as exc:
            raise CurrentTransformationError(
                "fixture references an unresolved provider team identity"
            ) from exc
        fixture = Fixture(
            id=canonical_fixture_id(
                response.scope.competition_id,
                response.scope.season_id,
                home.id,
                away.id,
            ),
            competition_id=response.scope.competition_id,
            season_id=response.scope.season_id,
            kickoff_at=observation.kickoff.kickoff_at,
            kickoff_precision=observation.kickoff.precision,
            home_team_id=home.id,
            away_team_id=away.id,
            status=observation.status,
            matchweek=observation.matchweek,
            referee=observation.referee,
            source_references=(
                SourceFixtureReference(
                    source_id=observation.provider_fixture_id.source_id,
                    external_id=observation.provider_fixture_id.external_id,
                ),
            ),
        )
        transformed.append(
            CanonicalCurrentFixture(
                fixture=fixture,
                observation=observation,
                capture=response.capture,
            )
        )
    return tuple(
        sorted(
            transformed,
            key=lambda item: (item.fixture.kickoff_at, item.fixture.id),
        )
    )


def current_fixture_batches(
    fixtures: Sequence[CanonicalCurrentFixture],
) -> tuple[CurrentFixtureBatch, ...]:
    """Build deterministic batches using the retained provider-local date."""

    identities = tuple(item.fixture.id for item in fixtures)
    if len(identities) != len(set(identities)):
        raise CurrentTransformationError(
            "current fixture identity occurs more than once"
        )
    timezones = {item.source_timezone for item in fixtures}
    if len(timezones) > 1:
        raise CurrentTransformationError(
            "one current fixture snapshot must use one source timezone"
        )
    by_date: dict[date, list[CanonicalCurrentFixture]] = defaultdict(list)
    for item in fixtures:
        by_date[item.source_local_date].append(item)

    batches: list[CurrentFixtureBatch] = []
    for local_date in sorted(by_date):
        date_fixtures = by_date[local_date]
        timezone_name = date_fixtures[0].source_timezone
        knowledge_at = max(item.capture.retrieved_at for item in date_fixtures)
        if any(
            item.fixture.kickoff_precision is KickoffPrecision.DATE_ONLY
            for item in date_fixtures
        ):
            local_start = datetime.combine(
                local_date,
                time.min,
                tzinfo=ZoneInfo(timezone_name),
            ).astimezone(UTC)
            batches.append(
                CurrentFixtureBatch(
                    feature_cutoff_at=local_start - timedelta(microseconds=1),
                    knowledge_available_at=knowledge_at,
                    source_timezone=timezone_name,
                    source_local_date=local_date,
                    fixtures=tuple(
                        sorted(date_fixtures, key=lambda item: item.fixture.id)
                    ),
                    is_date_only_batch=True,
                )
            )
            continue
        by_kickoff: dict[datetime, list[CanonicalCurrentFixture]] = defaultdict(list)
        for item in date_fixtures:
            by_kickoff[item.fixture.kickoff_at].append(item)
        for kickoff_at in sorted(by_kickoff):
            kickoff_fixtures = by_kickoff[kickoff_at]
            batches.append(
                CurrentFixtureBatch(
                    feature_cutoff_at=kickoff_at,
                    knowledge_available_at=max(
                        item.capture.retrieved_at for item in kickoff_fixtures
                    ),
                    source_timezone=timezone_name,
                    source_local_date=local_date,
                    fixtures=tuple(
                        sorted(kickoff_fixtures, key=lambda item: item.fixture.id)
                    ),
                    is_date_only_batch=False,
                )
            )
    return tuple(batches)
