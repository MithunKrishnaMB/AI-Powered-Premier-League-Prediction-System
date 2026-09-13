"""Order-independent deterministic sampling from explicit score distributions."""

from __future__ import annotations

import hashlib
from math import isfinite
from typing import Final
from uuid import UUID

from pl_platform.domain.simulation import (
    FixtureScorelineDistribution,
    SampledFixtureResult,
    Scoreline,
    SimulationContractError,
    SimulationFixture,
    deterministic_sampled_fixture_result_id,
)

_UINT64_SCALE: Final = 2**64


def deterministic_fixture_uniform(
    *,
    simulation_seed: int,
    simulation_index: int,
    fixture_id: UUID,
) -> float:
    """Return a stateless SHA-256-derived value in the half-open unit interval."""

    if (
        isinstance(simulation_seed, bool)
        or not isinstance(simulation_seed, int)
        or not 0 <= simulation_seed < _UINT64_SCALE
    ):
        raise SimulationContractError("simulation seed must be an unsigned 64-bit int")
    if (
        isinstance(simulation_index, bool)
        or not isinstance(simulation_index, int)
        or simulation_index < 0
    ):
        raise SimulationContractError("simulation index must be a non-negative int")
    identity = f"1|{simulation_seed}|{simulation_index}|{fixture_id}".encode()
    integer = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big")
    return integer / _UINT64_SCALE


def select_scoreline(
    distribution: FixtureScorelineDistribution,
    draw: float,
) -> Scoreline:
    """Select by canonical inverse CDF using a value in ``[0, 1)``."""

    if (
        isinstance(draw, bool)
        or not isinstance(draw, float)
        or not isfinite(draw)
        or not 0.0 <= draw < 1.0
    ):
        raise SimulationContractError("scoreline draw must be a finite float in [0, 1)")
    cumulative = 0.0
    for item in distribution.probabilities:
        cumulative += item.probability
        if draw < cumulative:
            return item.scoreline
    return distribution.probabilities[-1].scoreline


def sample_fixture_scoreline(
    fixture: SimulationFixture,
    *,
    simulation_seed: int,
    simulation_index: int,
) -> SampledFixtureResult:
    """Sample one fixture without mutable RNG state or fixture-order dependence."""

    draw = deterministic_fixture_uniform(
        simulation_seed=simulation_seed,
        simulation_index=simulation_index,
        fixture_id=fixture.fixture_id,
    )
    scoreline = select_scoreline(fixture.scoreline_distribution, draw)
    result_id = deterministic_sampled_fixture_result_id(
        distribution_id=fixture.scoreline_distribution.id,
        simulation_seed=simulation_seed,
        simulation_index=simulation_index,
        scoreline=scoreline,
    )
    return SampledFixtureResult(
        fixture_id=fixture.fixture_id,
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
        scoreline=scoreline,
        id=result_id,
        distribution_id=fixture.scoreline_distribution.id,
        simulation_seed=simulation_seed,
        simulation_index=simulation_index,
    )
