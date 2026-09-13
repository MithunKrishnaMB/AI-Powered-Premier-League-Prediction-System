"""Deterministic scoreline sampling and Premier League table mechanics."""

from pl_platform.simulation.aggregate import (
    SeasonSimulationSummary,
    TeamSimulationSummary,
    aggregate_simulations,
)
from pl_platform.simulation.scorelines import sample_fixture_scoreline
from pl_platform.simulation.table import (
    UnresolvedTableTieError,
    apply_match_result,
    build_league_table,
    rank_final_table,
)
from pl_platform.simulation.vectorized import (
    SIMULATION_COUNT,
    VectorizedSimulationResult,
    simulate_season_10k,
)

__all__ = [
    "SIMULATION_COUNT",
    "SeasonSimulationSummary",
    "TeamSimulationSummary",
    "UnresolvedTableTieError",
    "VectorizedSimulationResult",
    "aggregate_simulations",
    "apply_match_result",
    "build_league_table",
    "rank_final_table",
    "sample_fixture_scoreline",
    "simulate_season_10k",
]
