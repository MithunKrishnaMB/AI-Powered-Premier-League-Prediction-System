"""Aggregate deterministic simulation matrices into probability summaries."""

from __future__ import annotations

import hashlib
import json
from math import fsum, isclose
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.simulation import SimulationContractError
from pl_platform.simulation.vectorized import (
    SIMULATION_ALGORITHM_VERSION,
    SIMULATION_COUNT,
    VectorizedSimulationResult,
)

Probability = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class TeamSimulationSummary(BaseModel):
    """Position and threshold probabilities for one canonical team."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: UUID
    expected_points: FiniteFloat
    expected_goals_for: FiniteFloat
    expected_goals_against: FiniteFloat
    expected_goal_difference: FiniteFloat
    position_probabilities: tuple[Probability, ...] = Field(
        min_length=20, max_length=20
    )
    champion_probability: Probability
    top_four_probability: Probability
    top_six_probability: Probability
    relegation_probability: Probability

    @model_validator(mode="after")
    def derived_probabilities_must_match_positions(self) -> Self:
        if not isclose(
            fsum(self.position_probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("team position probabilities must sum to one")
        expected = (
            self.position_probabilities[0],
            fsum(self.position_probabilities[:4]),
            fsum(self.position_probabilities[:6]),
            fsum(self.position_probabilities[17:]),
        )
        observed = (
            self.champion_probability,
            self.top_four_probability,
            self.top_six_probability,
            self.relegation_probability,
        )
        if any(
            not isclose(actual, derived, rel_tol=0.0, abs_tol=1e-12)
            for actual, derived in zip(observed, expected, strict=True)
        ):
            raise ValueError("threshold probabilities do not match positions")
        if not isclose(
            self.expected_goal_difference,
            self.expected_goals_for - self.expected_goals_against,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("expected goal difference does not match goal means")
        return self


def deterministic_summary_id(
    simulation_id: UUID,
    season_id: str,
    teams: tuple[TeamSimulationSummary, ...],
) -> UUID:
    payload = {
        "algorithm_version": SIMULATION_ALGORITHM_VERSION,
        "season_id": season_id,
        "simulation_count": SIMULATION_COUNT,
        "simulation_id": str(simulation_id),
        "teams": tuple(team.model_dump(mode="json") for team in teams),
    }
    serialized = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return uuid5(NAMESPACE_URL, f"pl-platform:simulation-summary:{digest}")


class SeasonSimulationSummary(BaseModel):
    """Complete aggregate with fixed league-wide probability invariants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    summary_id: UUID
    simulation_id: UUID
    algorithm_version: Literal[1] = SIMULATION_ALGORITHM_VERSION
    simulation_count: Literal[10000] = SIMULATION_COUNT
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    teams: tuple[TeamSimulationSummary, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def league_probability_mass_must_be_complete(self) -> Self:
        team_ids = tuple(team.team_id for team in self.teams)
        if team_ids != tuple(sorted(set(team_ids), key=lambda value: value.int)):
            raise ValueError("simulation summary team IDs must be unique and ordered")
        for position in range(20):
            if not isclose(
                fsum(team.position_probabilities[position] for team in self.teams),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("each final position must contain unit probability")
        thresholds = (
            ("champion", 1.0, (team.champion_probability for team in self.teams)),
            ("top four", 4.0, (team.top_four_probability for team in self.teams)),
            ("top six", 6.0, (team.top_six_probability for team in self.teams)),
            ("relegation", 3.0, (team.relegation_probability for team in self.teams)),
        )
        for name, expected, values in thresholds:
            if not isclose(fsum(values), expected, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"{name} probability mass is incomplete")
        expected_id = deterministic_summary_id(
            self.simulation_id,
            self.season_id,
            self.teams,
        )
        if self.summary_id != expected_id:
            raise ValueError("simulation summary ID does not match its run")
        return self


def aggregate_simulations(
    result: VectorizedSimulationResult,
) -> SeasonSimulationSummary:
    """Aggregate all 10,000 runs, including fractional unresolved-tie mass."""

    positions = result.position_mass.mean(axis=0, dtype=np.float64)
    expected_points = result.points.mean(axis=0, dtype=np.float64)
    expected_for = result.goals_for.mean(axis=0, dtype=np.float64)
    expected_against = result.goals_against.mean(axis=0, dtype=np.float64)
    teams = tuple(
        TeamSimulationSummary(
            team_id=team_id,
            expected_points=float(expected_points[index]),
            expected_goals_for=float(expected_for[index]),
            expected_goals_against=float(expected_against[index]),
            expected_goal_difference=float(
                expected_for[index] - expected_against[index]
            ),
            position_probabilities=tuple(float(value) for value in positions[index]),
            champion_probability=float(positions[index, 0]),
            top_four_probability=float(positions[index, :4].sum()),
            top_six_probability=float(positions[index, :6].sum()),
            relegation_probability=float(positions[index, 17:].sum()),
        )
        for index, team_id in enumerate(result.team_ids)
    )
    summary_id = deterministic_summary_id(result.simulation_id, result.season_id, teams)
    try:
        return SeasonSimulationSummary(
            summary_id=summary_id,
            simulation_id=result.simulation_id,
            season_id=result.season_id,
            teams=teams,
        )
    except ValueError as exc:
        raise SimulationContractError(
            "simulation aggregation invariants failed"
        ) from exc
