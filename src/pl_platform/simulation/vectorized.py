"""Vectorized, reproducible execution of exactly 10,000 season simulations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
import numpy.typing as npt

from pl_platform.domain.simulation import (
    MAX_SIMULATED_GOALS,
    SeasonSimulationInput,
    SimulationContractError,
)
from pl_platform.simulation.scorelines import deterministic_fixture_uniform
from pl_platform.simulation.table import build_league_table

SIMULATION_ALGORITHM_VERSION: Final = 1
SIMULATION_COUNT: Final = 10_000
_SIMULATION_NAMESPACE: Final = "pl-platform:vectorized-season-simulation"


@dataclass(frozen=True, slots=True)
class VectorizedSimulationResult:
    """Read-only matrices for one deterministic 10,000-run simulation batch."""

    simulation_id: UUID
    season_id: str
    simulation_seed: int
    team_ids: tuple[UUID, ...]
    fixture_ids: tuple[UUID, ...]
    points: npt.NDArray[np.int64]
    goals_for: npt.NDArray[np.int64]
    goals_against: npt.NDArray[np.int64]
    sampled_home_goals: npt.NDArray[np.int16]
    sampled_away_goals: npt.NDArray[np.int16]
    position_mass: npt.NDArray[np.float64]

    def __post_init__(self) -> None:
        team_count = len(self.team_ids)
        fixture_count = len(self.fixture_ids)
        matrix_shape = (SIMULATION_COUNT, team_count)
        sample_shape = (SIMULATION_COUNT, fixture_count)
        if team_count != 20 or self.team_ids != tuple(
            sorted(set(self.team_ids), key=lambda value: value.int)
        ):
            raise SimulationContractError("simulation result requires 20 unique teams")
        if len(set(self.fixture_ids)) != fixture_count:
            raise SimulationContractError(
                "simulation result fixture IDs must be unique"
            )
        integer_matrices = (self.points, self.goals_for, self.goals_against)
        if any(value.shape != matrix_shape for value in integer_matrices):
            raise SimulationContractError("simulation table matrix shape is invalid")
        if any(value.dtype != np.dtype(np.int64) for value in integer_matrices):
            raise SimulationContractError("simulation table matrices must use int64")
        samples = (self.sampled_home_goals, self.sampled_away_goals)
        if any(value.shape != sample_shape for value in samples):
            raise SimulationContractError("sampled score matrix shape is invalid")
        if any(value.dtype != np.dtype(np.int16) for value in samples):
            raise SimulationContractError("sampled score matrices must use int16")
        if self.position_mass.shape != (SIMULATION_COUNT, team_count, team_count):
            raise SimulationContractError("position-mass tensor shape is invalid")
        if self.position_mass.dtype != np.dtype(np.float64):
            raise SimulationContractError("position mass must use float64")
        if (
            any(np.any(value < 0) for value in integer_matrices)
            or any(np.any(value < 0) for value in samples)
            or any(np.any(value > MAX_SIMULATED_GOALS) for value in samples)
            or not np.isfinite(self.position_mass).all()
            or np.any(self.position_mass < 0.0)
            or np.any(self.position_mass > 1.0)
        ):
            raise SimulationContractError("simulation result contains invalid values")
        if not np.allclose(
            self.position_mass.sum(axis=1),
            1.0,
            rtol=0.0,
            atol=1e-12,
        ) or not np.allclose(
            self.position_mass.sum(axis=2),
            1.0,
            rtol=0.0,
            atol=1e-12,
        ):
            raise SimulationContractError("position mass must be doubly stochastic")
        for value in (*integer_matrices, *samples, self.position_mass):
            value.flags.writeable = False


def simulation_identity_bytes(
    simulation_input: SeasonSimulationInput,
    simulation_seed: int,
) -> bytes:
    """Return exact bytes binding a run to its ordered input and algorithm."""

    if (
        isinstance(simulation_seed, bool)
        or not isinstance(simulation_seed, int)
        or not 0 <= simulation_seed < 2**64
    ):
        raise SimulationContractError("simulation seed must be an unsigned 64-bit int")

    payload = {
        "algorithm_version": SIMULATION_ALGORITHM_VERSION,
        "completed_matches": tuple(
            match.model_dump(mode="json")
            for match in simulation_input.completed_matches
        ),
        "competition_id": simulation_input.competition_id,
        "remaining_distributions": tuple(
            {
                "distribution_id": str(fixture.scoreline_distribution.id),
                "fixture_id": str(fixture.fixture_id),
                "kickoff_at": fixture.kickoff_at.isoformat(),
                "kickoff_precision": fixture.kickoff_precision.value,
            }
            for fixture in simulation_input.remaining_fixtures
        ),
        "schema_version": simulation_input.schema_version,
        "season_id": simulation_input.season_id,
        "simulation_count": SIMULATION_COUNT,
        "simulation_seed": simulation_seed,
        "team_ids": tuple(str(team_id) for team_id in simulation_input.team_ids),
    }
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def deterministic_simulation_id(
    simulation_input: SeasonSimulationInput,
    simulation_seed: int,
) -> UUID:
    """Bind a run to the complete ordered single-season input and algorithm."""

    digest = hashlib.sha256(
        simulation_identity_bytes(simulation_input, simulation_seed)
    ).hexdigest()
    return uuid5(NAMESPACE_URL, f"{_SIMULATION_NAMESPACE}:{digest}")


def _fixture_draws(simulation_seed: int, fixture_id: UUID) -> npt.NDArray[np.float64]:
    return np.fromiter(
        (
            deterministic_fixture_uniform(
                simulation_seed=simulation_seed,
                simulation_index=simulation_index,
                fixture_id=fixture_id,
            )
            for simulation_index in range(SIMULATION_COUNT)
        ),
        dtype=np.float64,
        count=SIMULATION_COUNT,
    )


def _sample_scores(
    simulation_input: SeasonSimulationInput,
    simulation_seed: int,
) -> tuple[npt.NDArray[np.int16], npt.NDArray[np.int16]]:
    fixture_count = len(simulation_input.remaining_fixtures)
    home_goals = np.empty((SIMULATION_COUNT, fixture_count), dtype=np.int16)
    away_goals = np.empty((SIMULATION_COUNT, fixture_count), dtype=np.int16)
    for fixture_index, fixture in enumerate(simulation_input.remaining_fixtures):
        scorelines = fixture.scoreline_distribution.probabilities
        if len(scorelines) == 1:
            home_goals[:, fixture_index] = scorelines[0].scoreline.home_goals
            away_goals[:, fixture_index] = scorelines[0].scoreline.away_goals
            continue
        probabilities = np.asarray(
            [item.probability for item in fixture.scoreline_distribution.probabilities],
            dtype=np.float64,
        )
        cumulative = np.cumsum(probabilities, dtype=np.float64)
        cumulative[-1] = 1.0
        selected = np.searchsorted(
            cumulative,
            _fixture_draws(simulation_seed, fixture.fixture_id),
            side="right",
        )
        home_values = np.asarray(
            [item.scoreline.home_goals for item in scorelines],
            dtype=np.int16,
        )
        away_values = np.asarray(
            [item.scoreline.away_goals for item in scorelines],
            dtype=np.int16,
        )
        home_goals[:, fixture_index] = home_values[selected]
        away_goals[:, fixture_index] = away_values[selected]
    return home_goals, away_goals


def _table_matrices(
    simulation_input: SeasonSimulationInput,
    home_goals: npt.NDArray[np.int16],
    away_goals: npt.NDArray[np.int16],
) -> tuple[
    npt.NDArray[np.int64],
    npt.NDArray[np.int64],
    npt.NDArray[np.int64],
]:
    initial = build_league_table(
        simulation_input.team_ids,
        simulation_input.completed_matches,
    )
    initial_points = np.asarray([row.points for row in initial.rows], dtype=np.int64)
    initial_for = np.asarray([row.goals_for for row in initial.rows], dtype=np.int64)
    initial_against = np.asarray(
        [row.goals_against for row in initial.rows], dtype=np.int64
    )
    points = np.broadcast_to(initial_points, (SIMULATION_COUNT, 20)).copy()
    goals_for = np.broadcast_to(initial_for, (SIMULATION_COUNT, 20)).copy()
    goals_against = np.broadcast_to(initial_against, (SIMULATION_COUNT, 20)).copy()
    team_index = {team_id: index for index, team_id in enumerate(initial.team_ids)}
    for fixture_index, fixture in enumerate(simulation_input.remaining_fixtures):
        home_index = team_index[fixture.home_team_id]
        away_index = team_index[fixture.away_team_id]
        home = home_goals[:, fixture_index].astype(np.int64, copy=False)
        away = away_goals[:, fixture_index].astype(np.int64, copy=False)
        goals_for[:, home_index] += home
        goals_against[:, home_index] += away
        goals_for[:, away_index] += away
        goals_against[:, away_index] += home
        draw = home == away
        points[:, home_index] += 3 * (home > away) + draw
        points[:, away_index] += 3 * (away > home) + draw
    return points, goals_for, goals_against


def _head_to_head(
    group: tuple[int, ...],
    *,
    simulation_index: int,
    simulation_input: SeasonSimulationInput,
    team_index: dict[UUID, int],
    home_goals: npt.NDArray[np.int16],
    away_goals: npt.NDArray[np.int16],
) -> dict[int, tuple[int, int]]:
    members = set(group)
    points: defaultdict[int, int] = defaultdict(int)
    away_goal_counts: defaultdict[int, int] = defaultdict(int)

    def observe(
        home_team_id: UUID,
        away_team_id: UUID,
        home_goals_value: int,
        away_goals_value: int,
    ) -> None:
        home_index = team_index[home_team_id]
        away_index = team_index[away_team_id]
        if home_index not in members or away_index not in members:
            return
        away_goal_counts[away_index] += away_goals_value
        if home_goals_value > away_goals_value:
            points[home_index] += 3
        elif away_goals_value > home_goals_value:
            points[away_index] += 3
        else:
            points[home_index] += 1
            points[away_index] += 1

    for match in simulation_input.completed_matches:
        observe(
            match.home_team_id,
            match.away_team_id,
            match.scoreline.home_goals,
            match.scoreline.away_goals,
        )
    for fixture_index, fixture in enumerate(simulation_input.remaining_fixtures):
        observe(
            fixture.home_team_id,
            fixture.away_team_id,
            int(home_goals[simulation_index, fixture_index]),
            int(away_goals[simulation_index, fixture_index]),
        )
    return {member: (points[member], away_goal_counts[member]) for member in members}


def _position_mass(
    simulation_input: SeasonSimulationInput,
    points: npt.NDArray[np.int64],
    goals_for: npt.NDArray[np.int64],
    goals_against: npt.NDArray[np.int64],
    home_goals: npt.NDArray[np.int16],
    away_goals: npt.NDArray[np.int16],
) -> npt.NDArray[np.float64]:
    goal_difference = goals_for - goals_against
    primary_order = np.lexsort((-goals_for, -goal_difference, -points), axis=1)
    mass = np.zeros((SIMULATION_COUNT, 20, 20), dtype=np.float64)
    team_index = {
        team_id: index for index, team_id in enumerate(simulation_input.team_ids)
    }
    for simulation_index in range(SIMULATION_COUNT):
        ordered = tuple(int(value) for value in primary_order[simulation_index])
        cursor = 0
        while cursor < 20:
            primary = (
                int(points[simulation_index, ordered[cursor]]),
                int(goal_difference[simulation_index, ordered[cursor]]),
                int(goals_for[simulation_index, ordered[cursor]]),
            )
            end = cursor + 1
            while end < 20:
                candidate = ordered[end]
                candidate_primary = (
                    int(points[simulation_index, candidate]),
                    int(goal_difference[simulation_index, candidate]),
                    int(goals_for[simulation_index, candidate]),
                )
                if candidate_primary != primary:
                    break
                end += 1
            group = ordered[cursor:end]
            if len(group) == 1:
                mass[simulation_index, group[0], cursor] = 1.0
                cursor = end
                continue
            head_to_head = _head_to_head(
                group,
                simulation_index=simulation_index,
                simulation_input=simulation_input,
                team_index=team_index,
                home_goals=home_goals,
                away_goals=away_goals,
            )
            secondary = tuple(
                sorted(
                    group,
                    key=lambda value: head_to_head[value],
                    reverse=True,
                )
            )
            secondary_cursor = 0
            while secondary_cursor < len(secondary):
                secondary_value = head_to_head[secondary[secondary_cursor]]
                secondary_end = secondary_cursor + 1
                while (
                    secondary_end < len(secondary)
                    and head_to_head[secondary[secondary_end]] == secondary_value
                ):
                    secondary_end += 1
                unresolved = secondary[secondary_cursor:secondary_end]
                slot_start = cursor + secondary_cursor
                slot_end = cursor + secondary_end
                weight = 1.0 / len(unresolved)
                for member in unresolved:
                    mass[simulation_index, member, slot_start:slot_end] = weight
                secondary_cursor = secondary_end
            cursor = end
    return mass


def simulate_season_10k(
    simulation_input: SeasonSimulationInput,
    *,
    simulation_seed: int,
) -> VectorizedSimulationResult:
    """Execute exactly 10,000 simulations using vectorized scores and tables."""

    simulation_id = deterministic_simulation_id(simulation_input, simulation_seed)
    home_goals, away_goals = _sample_scores(simulation_input, simulation_seed)
    points, goals_for, goals_against = _table_matrices(
        simulation_input,
        home_goals,
        away_goals,
    )
    position_mass = _position_mass(
        simulation_input,
        points,
        goals_for,
        goals_against,
        home_goals,
        away_goals,
    )
    if not all(
        isfinite(float(value))
        for value in (
            points.mean(),
            goals_for.mean(),
            goals_against.mean(),
            position_mass.mean(),
        )
    ):
        raise SimulationContractError("simulation produced a non-finite aggregate")
    return VectorizedSimulationResult(
        simulation_id=simulation_id,
        season_id=simulation_input.season_id,
        simulation_seed=simulation_seed,
        team_ids=simulation_input.team_ids,
        fixture_ids=tuple(
            fixture.fixture_id for fixture in simulation_input.remaining_fixtures
        ),
        points=points,
        goals_for=goals_for,
        goals_against=goals_against,
        sampled_home_goals=home_goals,
        sampled_away_goals=away_goals,
        position_mass=position_mass,
    )
