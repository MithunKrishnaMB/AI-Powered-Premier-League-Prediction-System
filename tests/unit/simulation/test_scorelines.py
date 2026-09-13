"""Tests for Step 4.5 deterministic scoreline sampling."""

from uuid import UUID

import pytest

from pl_platform.domain.simulation import (
    Scoreline,
    ScorelineProbability,
    SimulationContractError,
)
from pl_platform.simulation.scorelines import (
    deterministic_fixture_uniform,
    sample_fixture_scoreline,
    select_scoreline,
)
from tests.unit.simulation.helpers import distribution, simulation_fixture


def test_scoreline_sampling_is_stable_and_identity_bound() -> None:
    fixture = simulation_fixture()

    first = sample_fixture_scoreline(
        fixture,
        simulation_seed=20260913,
        simulation_index=17,
    )
    second = sample_fixture_scoreline(
        fixture,
        simulation_seed=20260913,
        simulation_index=17,
    )

    assert first == second
    assert first.fixture_id == fixture.fixture_id
    assert first.distribution_id == fixture.scoreline_distribution.id
    assert (
        0.0
        <= deterministic_fixture_uniform(
            simulation_seed=20260913,
            simulation_index=17,
            fixture_id=fixture.fixture_id,
        )
        < 1.0
    )


def test_stateless_draws_do_not_depend_on_fixture_iteration_order() -> None:
    fixtures = (simulation_fixture(UUID(int=101)), simulation_fixture(UUID(int=102)))
    forward = {
        fixture.fixture_id: sample_fixture_scoreline(
            fixture,
            simulation_seed=8,
            simulation_index=2,
        )
        for fixture in fixtures
    }
    reverse = {
        fixture.fixture_id: sample_fixture_scoreline(
            fixture,
            simulation_seed=8,
            simulation_index=2,
        )
        for fixture in reversed(fixtures)
    }

    assert forward == reverse


def test_inverse_cdf_honors_canonical_boundaries_and_rounding_tail() -> None:
    probabilities = (
        ScorelineProbability(
            scoreline=Scoreline(home_goals=0, away_goals=0),
            probability=0.5,
        ),
        ScorelineProbability(
            scoreline=Scoreline(home_goals=1, away_goals=0),
            probability=0.4999999999995,
        ),
    )
    value = distribution(probabilities=probabilities)

    assert select_scoreline(value, 0.0).home_goals == 0
    assert select_scoreline(value, 0.5).home_goals == 1
    assert select_scoreline(value, 0.9999999999999).home_goals == 1


@pytest.mark.parametrize(
    ("seed", "index"),
    ((-1, 0), (2**64, 0), (True, 0), (0, -1), (0, True)),
)
def test_draw_identity_rejects_invalid_seed_or_index(seed: int, index: int) -> None:
    with pytest.raises(SimulationContractError):
        deterministic_fixture_uniform(
            simulation_seed=seed,
            simulation_index=index,
            fixture_id=UUID(int=1),
        )


@pytest.mark.parametrize("draw", (-0.1, 1.0, float("nan"), True, 0))
def test_inverse_cdf_rejects_invalid_draw(draw: object) -> None:
    with pytest.raises(SimulationContractError):
        select_scoreline(distribution(), draw)  # type: ignore[arg-type]
