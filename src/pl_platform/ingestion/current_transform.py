"""Pure provider-neutral transformations for current-season observations."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from uuid import UUID
from zoneinfo import ZoneInfo

from pl_platform.domain.current import (
    CompletedFixtureResult,
    CurrentSeasonFixture,
    CurrentSeasonScope,
    CurrentSeasonTeam,
    ProviderTeamIdentifier,
    StandingRow,
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
    CompletedResultsResponse,
    CurrentSeasonFixturesResponse,
    CurrentSeasonTeamsResponse,
    FixtureStatusResponse,
    ProviderResponseCapture,
    StandingsResponse,
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
    status_observed_at: datetime | None = None

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


@dataclass(frozen=True, slots=True)
class CanonicalCompletedResult:
    fixture_id: UUID
    competition_id: str
    season_id: str
    home_team_id: UUID
    away_team_id: UUID
    observation: CompletedFixtureResult
    capture: ProviderResponseCapture


@dataclass(frozen=True, slots=True)
class CanonicalStandingRow:
    team_id: UUID
    observation: StandingRow


@dataclass(frozen=True, slots=True)
class CanonicalStandingsSnapshot:
    competition_id: str
    season_id: str
    rows: tuple[CanonicalStandingRow, ...]
    capture: ProviderResponseCapture


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


def transform_fixture_statuses(
    response: FixtureStatusResponse,
    current_fixtures: Sequence[CanonicalCurrentFixture],
    season: PremierLeagueSeason,
) -> tuple[CanonicalCurrentFixture, ...]:
    """Apply exact provider status observations to known canonical fixtures."""

    _validate_scope(response.scope, season)
    by_provider_id: dict[str, CanonicalCurrentFixture] = {}
    for current in current_fixtures:
        reference = current.observation.provider_fixture_id
        if (
            current.fixture.competition_id != response.scope.competition_id
            or current.fixture.season_id != response.scope.season_id
            or reference.source_id != response.scope.source_id
        ):
            raise CurrentTransformationError(
                "known fixture does not match the status response scope"
            )
        if reference.external_id in by_provider_id:
            raise CurrentTransformationError(
                "known fixtures repeat a provider fixture identity"
            )
        by_provider_id[reference.external_id] = current

    transformed: list[CanonicalCurrentFixture] = []
    for status in response.items:
        if status.status is FixtureStatus.FINISHED:
            raise CurrentTransformationError(
                "finished status requires completed-result reconciliation"
            )
        try:
            current = by_provider_id[status.provider_fixture_id.external_id]
        except KeyError as exc:
            raise CurrentTransformationError(
                "status references an unknown provider fixture identity"
            ) from exc
        transformed.append(
            CanonicalCurrentFixture(
                fixture=current.fixture.model_copy(update={"status": status.status}),
                observation=current.observation.model_copy(
                    update={
                        "status": status.status,
                        "provider_updated_at": status.provider_updated_at,
                    }
                ),
                capture=response.capture,
                status_observed_at=status.observed_at,
            )
        )
    return tuple(sorted(transformed, key=lambda item: item.fixture.id))


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


def _require_matching_resolution(
    scope: CurrentSeasonScope,
    resolution: CurrentTeamResolution,
) -> Mapping[str, CanonicalTeam]:
    if (
        resolution.source_id != scope.source_id
        or resolution.competition_id != scope.competition_id
        or resolution.season_id != scope.season_id
    ):
        raise CurrentTransformationError(
            "team resolution does not match the provider response scope"
        )
    return resolution.by_provider_id


def transform_completed_results(
    response: CompletedResultsResponse,
    resolution: CurrentTeamResolution,
    season: PremierLeagueSeason,
) -> tuple[CanonicalCompletedResult, ...]:
    """Resolve official results without weakening their retrieval-time boundary."""

    _validate_scope(response.scope, season)
    resolved = _require_matching_resolution(response.scope, resolution)
    transformed: list[CanonicalCompletedResult] = []
    for observation in response.items:
        try:
            home = resolved[observation.home_provider_team_id.external_id]
            away = resolved[observation.away_provider_team_id.external_id]
        except KeyError as exc:
            raise CurrentTransformationError(
                "completed result references an unresolved provider team identity"
            ) from exc
        transformed.append(
            CanonicalCompletedResult(
                fixture_id=canonical_fixture_id(
                    response.scope.competition_id,
                    response.scope.season_id,
                    home.id,
                    away.id,
                ),
                competition_id=response.scope.competition_id,
                season_id=response.scope.season_id,
                home_team_id=home.id,
                away_team_id=away.id,
                observation=observation,
                capture=response.capture,
            )
        )
    return tuple(sorted(transformed, key=lambda item: item.fixture_id))


def transform_current_standings(
    response: StandingsResponse,
    resolution: CurrentTeamResolution,
    season: PremierLeagueSeason,
) -> CanonicalStandingsSnapshot:
    """Resolve and require one complete, canonical current-season table."""

    _validate_scope(response.scope, season)
    resolved = _require_matching_resolution(response.scope, resolution)
    if len(response.items) != len(season.team_ids):
        raise CurrentTransformationError(
            "standings must contain the complete reviewed season membership"
        )
    expected_positions = tuple(range(1, len(season.team_ids) + 1))
    if tuple(item.position for item in response.items) != expected_positions:
        raise CurrentTransformationError(
            "standings positions must be consecutive from one"
        )
    rows: list[CanonicalStandingRow] = []
    for observation in response.items:
        try:
            team = resolved[observation.provider_team_id.external_id]
        except KeyError as exc:
            raise CurrentTransformationError(
                "standings reference an unresolved provider team identity"
            ) from exc
        rows.append(CanonicalStandingRow(team_id=team.id, observation=observation))
    if {row.team_id for row in rows} != set(season.team_ids):
        raise CurrentTransformationError(
            "standings do not match the reviewed season membership"
        )
    return CanonicalStandingsSnapshot(
        competition_id=response.scope.competition_id,
        season_id=response.scope.season_id,
        rows=tuple(rows),
        capture=response.capture,
    )


def reconcile_standings_with_results(
    snapshot: CanonicalStandingsSnapshot,
    results: Sequence[CanonicalCompletedResult],
) -> None:
    """Fail unless standings arithmetic equals results known by the snapshot."""

    totals = {
        row.team_id: {
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
        }
        for row in snapshot.rows
    }
    fixture_ids: set[UUID] = set()
    for result in results:
        if (
            result.competition_id != snapshot.competition_id
            or result.season_id != snapshot.season_id
        ):
            raise CurrentTransformationError(
                "completed-result scope does not match standings"
            )
        if result.fixture_id in fixture_ids:
            raise CurrentTransformationError("completed result occurs more than once")
        fixture_ids.add(result.fixture_id)
        if result.capture.retrieved_at > snapshot.capture.retrieved_at:
            continue
        try:
            home = totals[result.home_team_id]
            away = totals[result.away_team_id]
        except KeyError as exc:
            raise CurrentTransformationError(
                "completed result contains a team outside standings"
            ) from exc
        score = result.observation.full_time_score
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += score.home
        home["goals_against"] += score.away
        away["goals_for"] += score.away
        away["goals_against"] += score.home
        if score.home > score.away:
            home["won"] += 1
            away["lost"] += 1
        elif score.home < score.away:
            away["won"] += 1
            home["lost"] += 1
        else:
            home["drawn"] += 1
            away["drawn"] += 1
    for row in snapshot.rows:
        observation = row.observation
        actual = totals[row.team_id]
        expected = {
            "played": observation.played,
            "won": observation.won,
            "drawn": observation.drawn,
            "lost": observation.lost,
            "goals_for": observation.goals_for,
            "goals_against": observation.goals_against,
        }
        if actual != expected:
            raise CurrentTransformationError(
                "standings do not reconcile with completed results known at retrieval"
            )
