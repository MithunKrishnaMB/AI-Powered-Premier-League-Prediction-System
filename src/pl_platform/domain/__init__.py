"""Provider-independent football domain models."""

from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatistics,
    FixtureStatus,
    MatchOutcome,
    SourceFixtureReference,
    TeamMatchStatistics,
)
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonEntryStatus,
    SeasonRegistry,
    SeasonTeamMembership,
    load_season_registry,
)
from pl_platform.domain.teams import (
    CanonicalTeam,
    TeamRegistry,
    UnknownTeamAliasError,
    load_team_registry,
)

__all__ = [
    "CanonicalTeam",
    "Fixture",
    "FixtureScore",
    "FixtureStatistics",
    "FixtureStatus",
    "MatchOutcome",
    "PremierLeagueSeason",
    "SeasonEntryStatus",
    "SeasonRegistry",
    "SeasonTeamMembership",
    "SourceFixtureReference",
    "TeamMatchStatistics",
    "TeamRegistry",
    "UnknownTeamAliasError",
    "load_season_registry",
    "load_team_registry",
]
