"""Tests for Step 4.4 simulator domain structures."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome
from pl_platform.domain.simulation import (
    FixtureScorelineDistribution,
    PlayedFixture,
    Scoreline,
    ScorelineProbability,
    SeasonSimulationInput,
    SimulationFixture,
    deterministic_scoreline_distribution_id,
    simulation_fixture_batches,
)
from tests.unit.simulation.helpers import TEAM_IDS, distribution, simulation_fixture


@pytest.mark.parametrize(
    ("home", "away", "outcome"),
    (
        (2, 1, MatchOutcome.HOME_WIN),
        (1, 1, MatchOutcome.DRAW),
        (0, 3, MatchOutcome.AWAY_WIN),
    ),
)
def test_scoreline_exposes_canonical_outcome(
    home: int,
    away: int,
    outcome: MatchOutcome,
) -> None:
    assert Scoreline(home_goals=home, away_goals=away).outcome == outcome


def test_scoreline_distribution_has_stable_content_identity() -> None:
    first = distribution()
    second = distribution()

    assert first == second
    assert first.id == deterministic_scoreline_distribution_id(
        fixture_id=first.fixture_id,
        home_team_id=first.home_team_id,
        away_team_id=first.away_team_id,
        probabilities=first.probabilities,
    )


@pytest.mark.parametrize("mutation", ("order", "sum", "identity", "same_team"))
def test_scoreline_distribution_rejects_contract_drift(mutation: str) -> None:
    valid = distribution().model_dump(mode="python")
    if mutation == "order":
        valid["probabilities"] = tuple(reversed(valid["probabilities"]))
    elif mutation == "sum":
        valid["probabilities"][0]["probability"] = 0.1
    elif mutation == "identity":
        valid["id"] = UUID(int=999)
    else:
        valid["away_team_id"] = valid["home_team_id"]

    with pytest.raises(ValidationError):
        FixtureScorelineDistribution.model_validate(valid)


def test_simulation_fixture_binds_distribution_and_utc_kickoff() -> None:
    fixture = simulation_fixture()
    assert fixture.scoreline_distribution.fixture_id == fixture.fixture_id

    payload = fixture.model_dump(mode="python")
    payload["kickoff_at"] = datetime(2027, 1, 1, 15)
    with pytest.raises(ValidationError):
        SimulationFixture.model_validate(payload)

    payload = fixture.model_dump(mode="python")
    payload["home_team_id"] = TEAM_IDS[2]
    with pytest.raises(ValidationError):
        SimulationFixture.model_validate(payload)


def test_season_simulation_input_preserves_membership_and_order() -> None:
    earlier_id = UUID(int=102)
    later_id = UUID(int=101)
    earlier = simulation_fixture(
        earlier_id,
        TEAM_IDS[2],
        TEAM_IDS[3],
        datetime(2027, 2, 1, tzinfo=UTC),
        KickoffPrecision.DATE_ONLY,
    )
    later = simulation_fixture(
        later_id,
        TEAM_IDS[0],
        TEAM_IDS[1],
        datetime(2027, 2, 2, tzinfo=UTC),
    )
    completed = PlayedFixture(
        fixture_id=UUID(int=100),
        home_team_id=TEAM_IDS[4],
        away_team_id=TEAM_IDS[5],
        scoreline=Scoreline(home_goals=1, away_goals=1),
    )

    value = SeasonSimulationInput(
        season_id="2026-2027",
        team_ids=TEAM_IDS,
        completed_matches=(completed,),
        remaining_fixtures=(earlier, later),
    )

    assert value.remaining_fixtures == (earlier, later)
    assert earlier.kickoff_precision == KickoffPrecision.DATE_ONLY


def test_date_only_fixture_absorbs_exact_fixture_on_same_date() -> None:
    exact = simulation_fixture(
        UUID(int=101),
        TEAM_IDS[0],
        TEAM_IDS[1],
        datetime(2027, 2, 1, 15, tzinfo=UTC),
    )
    date_only = simulation_fixture(
        UUID(int=102),
        TEAM_IDS[2],
        TEAM_IDS[3],
        datetime(2027, 2, 1, 12, tzinfo=UTC),
        KickoffPrecision.DATE_ONLY,
    )

    (batch,) = simulation_fixture_batches((date_only, exact))
    value = SeasonSimulationInput(
        season_id="2026-2027",
        team_ids=TEAM_IDS,
        remaining_fixtures=batch.fixtures,
    )

    assert batch.is_date_only_batch
    assert batch.fixtures == (exact, date_only)
    assert value.remaining_fixtures == batch.fixtures


@pytest.mark.parametrize("mutation", ("team_order", "fixture_order", "duplicate"))
def test_season_simulation_input_rejects_noncanonical_identity(
    mutation: str,
) -> None:
    first = simulation_fixture()
    second = simulation_fixture(
        UUID(int=102),
        TEAM_IDS[2],
        TEAM_IDS[3],
        datetime(2027, 1, 2, 15, tzinfo=UTC),
    )
    teams = TEAM_IDS
    remaining: tuple[SimulationFixture, ...] = (first, second)
    completed: tuple[PlayedFixture, ...] = ()
    if mutation == "team_order":
        teams = tuple(reversed(teams))
    elif mutation == "fixture_order":
        remaining = tuple(reversed(remaining))
    else:
        completed = (
            PlayedFixture(
                fixture_id=first.fixture_id,
                home_team_id=first.home_team_id,
                away_team_id=first.away_team_id,
                scoreline=Scoreline(home_goals=0, away_goals=0),
            ),
        )

    with pytest.raises(ValidationError):
        SeasonSimulationInput(
            season_id="2026-2027",
            team_ids=teams,
            completed_matches=completed,
            remaining_fixtures=remaining,
        )


def test_probability_contract_is_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        ScorelineProbability(
            scoreline=Scoreline(home_goals=0, away_goals=0),
            probability="1",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        Scoreline(home_goals=41, away_goals=0)
