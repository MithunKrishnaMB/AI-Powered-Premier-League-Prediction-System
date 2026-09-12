"""Typed fixtures shared by feature-system unit tests."""

from datetime import UTC, date, datetime
from uuid import UUID

from pl_platform.domain.features import (
    CanonicalDatasetProvenance,
    SourceArtifactProvenance,
)
from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatistics,
    FixtureStatus,
    KickoffPrecision,
    SourceFixtureReference,
    TeamMatchStatistics,
)
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonEntryStatus,
    SeasonTeamMembership,
)

TEAM_IDS = tuple(UUID(int=index) for index in range(1, 21))


def make_season() -> PremierLeagueSeason:
    return PremierLeagueSeason(
        id="2025-2026",
        competition_id="eng-premier-league",
        starts_on=date(2025, 8, 1),
        ends_on=date(2026, 5, 31),
        completed=True,
        memberships=tuple(
            SeasonTeamMembership(
                team_id=team_id,
                entry_status=(
                    SeasonEntryStatus.PROMOTED
                    if index < 3
                    else SeasonEntryStatus.CONTINUED
                ),
                previous_competition_id=("eng-championship" if index < 3 else None),
            )
            for index, team_id in enumerate(TEAM_IDS)
        ),
    )


def make_provenance(
    *,
    competition_id: str = "eng-premier-league",
    season_id: str = "2025-2026",
    source_id: str = "verified-source",
) -> CanonicalDatasetProvenance:
    return CanonicalDatasetProvenance(
        dataset_id="canonical-fixtures-2025-2026",
        dataset_schema_version=2,
        competition_id=competition_id,
        season_id=season_id,
        fixtures_sha256="a" * 64,
        team_registry_schema_version=1,
        season_registry_schema_version=1,
        source=SourceArtifactProvenance(
            source_id=source_id,
            artifact_id="epl-2025-2026",
            sha256="b" * 64,
            captured_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
    )


def make_statistics(
    *,
    home_shots: int = 10,
    away_shots: int = 8,
) -> FixtureStatistics:
    return FixtureStatistics(
        home=TeamMatchStatistics(
            shots=home_shots,
            shots_on_target=4,
            fouls=11,
            yellow_cards=2,
            red_cards=0,
        ),
        away=TeamMatchStatistics(
            shots=away_shots,
            shots_on_target=3,
            fouls=13,
            yellow_cards=1,
            red_cards=0,
        ),
    )


def make_fixture(
    fixture_number: int,
    kickoff_at: datetime,
    home_team_id: UUID,
    away_team_id: UUID,
    *,
    home_goals: int = 1,
    away_goals: int = 0,
    kickoff_precision: KickoffPrecision = KickoffPrecision.EXACT,
    statistics: FixtureStatistics | None = None,
    competition_id: str = "eng-premier-league",
    season_id: str = "2025-2026",
    source_id: str = "verified-source",
    finished: bool = True,
) -> Fixture:
    score = FixtureScore(home=home_goals, away=away_goals)
    return Fixture(
        id=UUID(int=fixture_number),
        competition_id=competition_id,
        season_id=season_id,
        kickoff_at=kickoff_at,
        kickoff_precision=kickoff_precision,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        status=FixtureStatus.FINISHED if finished else FixtureStatus.SCHEDULED,
        full_time_score=score if finished else None,
        outcome=score.outcome if finished else None,
        statistics=statistics,
        source_references=(
            SourceFixtureReference(
                source_id=source_id,
                external_id=f"row:{fixture_number}",
            ),
        ),
    )
