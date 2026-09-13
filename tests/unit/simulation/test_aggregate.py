"""Step 4.8 aggregate probabilities and Step 4.9 league invariants."""

from math import fsum
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.simulation import SeasonSimulationInput
from pl_platform.simulation.aggregate import (
    SeasonSimulationSummary,
    aggregate_simulations,
)
from pl_platform.simulation.vectorized import simulate_season_10k
from tests.unit.simulation.helpers import TEAM_IDS


@pytest.fixture(scope="module")
def empty_summary() -> SeasonSimulationSummary:
    inputs = SeasonSimulationInput(
        season_id="2026-2027",
        team_ids=TEAM_IDS,
    )
    return aggregate_simulations(simulate_season_10k(inputs, simulation_seed=11))


def test_fractional_unresolved_ties_preserve_position_mass(
    empty_summary: SeasonSimulationSummary,
) -> None:
    assert len(empty_summary.teams) == 20
    for team in empty_summary.teams:
        assert team.position_probabilities == pytest.approx((0.05,) * 20)
        assert team.champion_probability == pytest.approx(0.05)
        assert team.top_four_probability == pytest.approx(0.2)
        assert team.top_six_probability == pytest.approx(0.3)
        assert team.relegation_probability == pytest.approx(0.15)


def test_aggregate_league_threshold_invariants(
    empty_summary: SeasonSimulationSummary,
) -> None:
    assert fsum(
        team.champion_probability for team in empty_summary.teams
    ) == pytest.approx(1.0)
    assert fsum(
        team.top_four_probability for team in empty_summary.teams
    ) == pytest.approx(4.0)
    assert fsum(
        team.top_six_probability for team in empty_summary.teams
    ) == pytest.approx(6.0)
    assert fsum(
        team.relegation_probability for team in empty_summary.teams
    ) == pytest.approx(3.0)
    for position in range(20):
        assert fsum(
            team.position_probabilities[position] for team in empty_summary.teams
        ) == pytest.approx(1.0)


def test_summary_identity_and_bytes_are_reproducible(
    empty_summary: SeasonSimulationSummary,
) -> None:
    repeated = empty_summary.model_validate_json(empty_summary.model_dump_json())
    assert repeated == empty_summary
    assert repeated.summary_id == empty_summary.summary_id


def test_summary_rejects_threshold_or_identity_drift(
    empty_summary: SeasonSimulationSummary,
) -> None:
    payload = empty_summary.model_dump(mode="python")
    payload["summary_id"] = UUID(int=999)
    with pytest.raises(ValidationError, match="summary ID"):
        type(empty_summary).model_validate(payload)

    payload = empty_summary.model_dump(mode="python")
    payload["teams"][0]["expected_points"] = 1.0
    with pytest.raises(ValidationError, match="summary ID"):
        type(empty_summary).model_validate(payload)

    payload = empty_summary.model_dump(mode="python")
    payload["teams"][0]["champion_probability"] = 0.0
    with pytest.raises(ValidationError, match="threshold probabilities"):
        type(empty_summary).model_validate(payload)
