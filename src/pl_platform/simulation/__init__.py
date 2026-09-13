"""Deterministic scoreline sampling and Premier League table mechanics."""

from pl_platform.simulation.scorelines import sample_fixture_scoreline
from pl_platform.simulation.table import (
    UnresolvedTableTieError,
    apply_match_result,
    build_league_table,
    rank_final_table,
)

__all__ = [
    "UnresolvedTableTieError",
    "apply_match_result",
    "build_league_table",
    "rank_final_table",
    "sample_fixture_scoreline",
]
