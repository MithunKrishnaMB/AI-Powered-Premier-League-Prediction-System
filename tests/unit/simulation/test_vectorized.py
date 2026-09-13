"""Step 4.7 vectorized-run and Step 4.9 reproducibility invariants."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
import pytest

from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.domain.simulation import (
    Scoreline,
    ScorelineProbability,
    SeasonSimulationInput,
    SimulationContractError,
    SimulationFixture,
)
from pl_platform.simulation.vectorized import (
    SIMULATION_COUNT,
    VectorizedSimulationResult,
    deterministic_simulation_id,
    simulate_season_10k,
)
from tests.unit.simulation.helpers import TEAM_IDS, distribution, simulation_fixture


def simulation_input() -> SeasonSimulationInput:
    fixtures = (
        simulation_fixture(
            UUID(int=101),
            TEAM_IDS[0],
            TEAM_IDS[1],
            datetime(2027, 1, 1, 15, tzinfo=UTC),
        ),
        simulation_fixture(
            UUID(int=102),
            TEAM_IDS[2],
            TEAM_IDS[3],
            datetime(2027, 1, 2, 15, tzinfo=UTC),
        ),
    )
    return SeasonSimulationInput(
        season_id="2026-2027",
        team_ids=TEAM_IDS,
        remaining_fixtures=fixtures,
    )


def test_vectorized_10k_run_is_exactly_reproducible() -> None:
    inputs = simulation_input()

    first = simulate_season_10k(inputs, simulation_seed=20260913)
    second = simulate_season_10k(inputs, simulation_seed=20260913)

    assert first.simulation_id == second.simulation_id
    assert first.points.shape == (SIMULATION_COUNT, 20)
    assert first.sampled_home_goals.shape == (SIMULATION_COUNT, 2)
    assert np.array_equal(first.points, second.points)
    assert np.array_equal(first.sampled_home_goals, second.sampled_home_goals)
    assert np.array_equal(first.position_mass, second.position_mass)
    assert not first.points.flags.writeable
    assert not first.position_mass.flags.writeable


def test_vectorized_sampling_tracks_explicit_distribution_mass() -> None:
    result = simulate_season_10k(simulation_input(), simulation_seed=99)
    first_fixture = tuple(
        (int(home), int(away))
        for home, away in zip(
            result.sampled_home_goals[:, 0],
            result.sampled_away_goals[:, 0],
            strict=True,
        )
    )

    frequencies = {
        score: first_fixture.count(score) / SIMULATION_COUNT
        for score in ((0, 0), (1, 0), (1, 1))
    }
    assert frequencies[(0, 0)] == pytest.approx(0.2, abs=0.02)
    assert frequencies[(1, 0)] == pytest.approx(0.5, abs=0.02)
    assert frequencies[(1, 1)] == pytest.approx(0.3, abs=0.02)


def test_vectorized_table_and_position_mass_invariants() -> None:
    result = simulate_season_10k(simulation_input(), simulation_seed=7)
    total_sampled_goals = result.sampled_home_goals.astype(np.int64).sum(
        axis=1
    ) + result.sampled_away_goals.astype(np.int64).sum(axis=1)

    assert np.array_equal(result.goals_for.sum(axis=1), total_sampled_goals)
    assert np.array_equal(
        result.goals_for.sum(axis=1), result.goals_against.sum(axis=1)
    )
    assert np.allclose(result.position_mass.sum(axis=1), 1.0)
    assert np.allclose(result.position_mass.sum(axis=2), 1.0)
    assert np.all((result.points.sum(axis=1) >= 4) & (result.points.sum(axis=1) <= 6))


def test_simulation_identity_changes_with_seed_and_rejects_invalid_seed() -> None:
    inputs = simulation_input()
    assert deterministic_simulation_id(inputs, 1) != deterministic_simulation_id(
        inputs, 2
    )
    with pytest.raises(SimulationContractError):
        deterministic_simulation_id(inputs, -1)


def test_vectorized_result_rejects_invalid_matrix_contract() -> None:
    result = simulate_season_10k(simulation_input(), simulation_seed=4)
    with pytest.raises(SimulationContractError, match="matrix shape"):
        VectorizedSimulationResult(
            simulation_id=result.simulation_id,
            season_id=result.season_id,
            simulation_seed=result.simulation_seed,
            team_ids=result.team_ids,
            fixture_ids=result.fixture_ids,
            points=np.zeros((1, 20), dtype=np.int64),
            goals_for=result.goals_for,
            goals_against=result.goals_against,
            sampled_home_goals=result.sampled_home_goals,
            sampled_away_goals=result.sampled_away_goals,
            position_mass=result.position_mass,
        )


def test_complete_double_round_robin_conserves_full_season_totals() -> None:
    deterministic_score = (
        ScorelineProbability(
            scoreline=Scoreline(home_goals=1, away_goals=0),
            probability=1.0,
        ),
    )
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    fixtures: list[SimulationFixture] = []
    identity = 1000
    for home_index, home_team_id in enumerate(TEAM_IDS):
        for away_index, away_team_id in enumerate(TEAM_IDS):
            if home_index == away_index:
                continue
            fixture_id = UUID(int=identity)
            fixtures.append(
                SimulationFixture(
                    fixture_id=fixture_id,
                    season_id="2026-2027",
                    kickoff_at=kickoff + timedelta(hours=identity - 1000),
                    kickoff_precision=KickoffPrecision.EXACT,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    scoreline_distribution=distribution(
                        fixture_id,
                        home_team_id,
                        away_team_id,
                        deterministic_score,
                    ),
                )
            )
            identity += 1
    inputs = SeasonSimulationInput(
        season_id="2026-2027",
        team_ids=TEAM_IDS,
        remaining_fixtures=tuple(fixtures),
    )

    result = simulate_season_10k(inputs, simulation_seed=42)

    assert len(result.fixture_ids) == 380
    assert np.all(result.sampled_home_goals == 1)
    assert np.all(result.sampled_away_goals == 0)
    assert np.all(result.points == 57)
    assert np.all(result.goals_for == 19)
    assert np.all(result.goals_against == 19)
    assert np.all(result.points.sum(axis=1) == 1_140)
    assert np.allclose(result.position_mass, 0.05)
