"""Shared deterministic simulation fixtures."""

from datetime import UTC, datetime
from uuid import UUID

from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.domain.simulation import (
    FixtureScorelineDistribution,
    Scoreline,
    ScorelineProbability,
    SimulationFixture,
    deterministic_scoreline_distribution_id,
)

TEAM_IDS = tuple(UUID(int=index) for index in range(1, 21))
FIXTURE_ID = UUID(int=101)


def distribution(
    fixture_id: UUID = FIXTURE_ID,
    home_team_id: UUID = TEAM_IDS[0],
    away_team_id: UUID = TEAM_IDS[1],
    probabilities: tuple[ScorelineProbability, ...] | None = None,
) -> FixtureScorelineDistribution:
    values = probabilities or (
        ScorelineProbability(
            scoreline=Scoreline(home_goals=0, away_goals=0),
            probability=0.2,
        ),
        ScorelineProbability(
            scoreline=Scoreline(home_goals=1, away_goals=0),
            probability=0.5,
        ),
        ScorelineProbability(
            scoreline=Scoreline(home_goals=1, away_goals=1),
            probability=0.3,
        ),
    )
    identity = deterministic_scoreline_distribution_id(
        fixture_id=fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        probabilities=values,
    )
    return FixtureScorelineDistribution(
        id=identity,
        fixture_id=fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        probabilities=values,
    )


def simulation_fixture(
    fixture_id: UUID = FIXTURE_ID,
    home_team_id: UUID = TEAM_IDS[0],
    away_team_id: UUID = TEAM_IDS[1],
    kickoff_at: datetime = datetime(2027, 1, 1, 15, tzinfo=UTC),
    kickoff_precision: KickoffPrecision = KickoffPrecision.EXACT,
) -> SimulationFixture:
    return SimulationFixture(
        fixture_id=fixture_id,
        season_id="2026-2027",
        kickoff_at=kickoff_at,
        kickoff_precision=kickoff_precision,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        scoreline_distribution=distribution(
            fixture_id,
            home_team_id,
            away_team_id,
        ),
    )
