"""Strict, provider-independent season-simulation domain contracts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from math import fsum, isclose
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome

SIMULATION_SCHEMA_VERSION: Final = 1
SIMULATION_NAMESPACE: Final = "pl-platform:season-simulation"
MAX_SIMULATED_GOALS: Final = 40
_PREMIER_LEAGUE_TIMEZONE: Final = ZoneInfo("Europe/London")

StrictNonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
Probability = Annotated[
    float,
    Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False),
]
SeasonId = Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")]


class SimulationContractError(ValueError):
    """Simulation data violates an immutable domain boundary."""


class Scoreline(BaseModel):
    """One bounded full-time scoreline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_goals: Annotated[int, Field(strict=True, ge=0, le=MAX_SIMULATED_GOALS)]
    away_goals: Annotated[int, Field(strict=True, ge=0, le=MAX_SIMULATED_GOALS)]

    @property
    def outcome(self) -> MatchOutcome:
        if self.home_goals > self.away_goals:
            return MatchOutcome.HOME_WIN
        if self.home_goals < self.away_goals:
            return MatchOutcome.AWAY_WIN
        return MatchOutcome.DRAW


class ScorelineProbability(BaseModel):
    """Probability mass assigned to one scoreline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoreline: Scoreline
    probability: Probability


def _identity_digest(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def deterministic_scoreline_distribution_id(
    *,
    fixture_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
    probabilities: tuple[ScorelineProbability, ...],
) -> UUID:
    """Bind a distribution identity to fixture, teams, order and exact mass."""

    digest = _identity_digest(
        {
            "fixture_id": str(fixture_id),
            "home_team_id": str(home_team_id),
            "away_team_id": str(away_team_id),
            "probabilities": tuple(
                probability.model_dump(mode="json") for probability in probabilities
            ),
            "schema_version": SIMULATION_SCHEMA_VERSION,
        }
    )
    return uuid5(
        NAMESPACE_URL,
        f"{SIMULATION_NAMESPACE}:scoreline-distribution:{digest}",
    )


class FixtureScorelineDistribution(BaseModel):
    """Explicit scoreline input; no classifier-to-score conversion is implied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    id: UUID
    fixture_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    probabilities: tuple[ScorelineProbability, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def distribution_must_be_canonical_and_complete(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("scoreline distribution teams must differ")
        scores = tuple(
            (
                probability.scoreline.home_goals,
                probability.scoreline.away_goals,
            )
            for probability in self.probabilities
        )
        if scores != tuple(sorted(set(scores))):
            raise ValueError("scoreline probabilities must be unique and ordered")
        if not isclose(
            fsum(item.probability for item in self.probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("scoreline probabilities must sum to one")
        expected_id = deterministic_scoreline_distribution_id(
            fixture_id=self.fixture_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            probabilities=self.probabilities,
        )
        if self.id != expected_id:
            raise ValueError("scoreline distribution ID does not match its contents")
        return self


class SimulationFixture(BaseModel):
    """One remaining fixture with an externally supplied score distribution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    fixture_id: UUID
    season_id: SeasonId
    kickoff_at: datetime
    kickoff_precision: KickoffPrecision
    home_team_id: UUID
    away_team_id: UUID
    scoreline_distribution: FixtureScorelineDistribution

    @model_validator(mode="after")
    def fixture_and_distribution_must_agree(self) -> Self:
        if self.kickoff_at.tzinfo is None or self.kickoff_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("simulation fixture kickoff must be timezone-aware UTC")
        distribution = self.scoreline_distribution
        if (
            self.home_team_id == self.away_team_id
            or distribution.fixture_id != self.fixture_id
            or distribution.home_team_id != self.home_team_id
            or distribution.away_team_id != self.away_team_id
        ):
            raise ValueError("simulation fixture does not match its score distribution")
        return self


def _fixture_competition_date(fixture: SimulationFixture) -> date:
    return fixture.kickoff_at.astimezone(_PREMIER_LEAGUE_TIMEZONE).date()


class SimulationFixtureBatch(BaseModel):
    """Fixtures sampled together under the point-in-time chronology policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixtures: tuple[SimulationFixture, ...] = Field(min_length=1)
    is_date_only_batch: bool

    @model_validator(mode="after")
    def batch_must_be_simultaneous_and_ordered(self) -> Self:
        if tuple(fixture.fixture_id for fixture in self.fixtures) != tuple(
            sorted(
                {fixture.fixture_id for fixture in self.fixtures},
                key=lambda value: value.int,
            )
        ):
            raise ValueError("simulation batch fixtures must be unique and ordered")
        if len({fixture.season_id for fixture in self.fixtures}) != 1:
            raise ValueError("simulation batch fixtures must share one season")
        if self.is_date_only_batch:
            if (
                not any(
                    fixture.kickoff_precision == KickoffPrecision.DATE_ONLY
                    for fixture in self.fixtures
                )
                or len({_fixture_competition_date(item) for item in self.fixtures}) != 1
            ):
                raise ValueError("date-only batch must contain one competition date")
        elif (
            any(
                fixture.kickoff_precision == KickoffPrecision.DATE_ONLY
                for fixture in self.fixtures
            )
            or len({fixture.kickoff_at for fixture in self.fixtures}) != 1
        ):
            raise ValueError("exact batch fixtures must share one kickoff")
        return self


def simulation_fixture_batches(
    fixtures: Sequence[SimulationFixture],
) -> tuple[SimulationFixtureBatch, ...]:
    """Apply the existing conservative Premier League simultaneous-batch rule."""

    identifiers = [fixture.fixture_id for fixture in fixtures]
    if len(identifiers) != len(set(identifiers)):
        raise SimulationContractError("simulation fixture ID occurs more than once")
    fixtures_by_date: defaultdict[date, list[SimulationFixture]] = defaultdict(list)
    for fixture in fixtures:
        fixtures_by_date[_fixture_competition_date(fixture)].append(fixture)
    batches: list[SimulationFixtureBatch] = []
    for fixture_date in sorted(fixtures_by_date):
        date_fixtures = fixtures_by_date[fixture_date]
        if any(
            fixture.kickoff_precision == KickoffPrecision.DATE_ONLY
            for fixture in date_fixtures
        ):
            batches.append(
                SimulationFixtureBatch(
                    fixtures=tuple(
                        sorted(date_fixtures, key=lambda item: item.fixture_id.int)
                    ),
                    is_date_only_batch=True,
                )
            )
            continue
        fixtures_by_kickoff: defaultdict[datetime, list[SimulationFixture]] = (
            defaultdict(list)
        )
        for fixture in date_fixtures:
            fixtures_by_kickoff[fixture.kickoff_at].append(fixture)
        for kickoff_at in sorted(fixtures_by_kickoff):
            batches.append(
                SimulationFixtureBatch(
                    fixtures=tuple(
                        sorted(
                            fixtures_by_kickoff[kickoff_at],
                            key=lambda item: item.fixture_id.int,
                        )
                    ),
                    is_date_only_batch=False,
                )
            )
    return tuple(batches)


class PlayedFixture(BaseModel):
    """A completed actual or sampled result accepted by the table engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    scoreline: Scoreline

    @model_validator(mode="after")
    def teams_must_differ(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("played fixture teams must differ")
        return self


def deterministic_sampled_fixture_result_id(
    *,
    distribution_id: UUID,
    simulation_seed: int,
    simulation_index: int,
    scoreline: Scoreline,
) -> UUID:
    digest = _identity_digest(
        {
            "distribution_id": str(distribution_id),
            "schema_version": SIMULATION_SCHEMA_VERSION,
            "scoreline": scoreline.model_dump(mode="json"),
            "simulation_index": simulation_index,
            "simulation_seed": simulation_seed,
        }
    )
    return uuid5(NAMESPACE_URL, f"{SIMULATION_NAMESPACE}:sampled-result:{digest}")


class SampledFixtureResult(PlayedFixture):
    """One reproducible scoreline draw with complete sampling identity."""

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    id: UUID
    distribution_id: UUID
    simulation_seed: Annotated[int, Field(strict=True, ge=0, lt=2**64)]
    simulation_index: StrictNonNegativeInt

    @model_validator(mode="after")
    def identity_must_match_draw(self) -> Self:
        expected = deterministic_sampled_fixture_result_id(
            distribution_id=self.distribution_id,
            simulation_seed=self.simulation_seed,
            simulation_index=self.simulation_index,
            scoreline=self.scoreline,
        )
        if self.id != expected:
            raise ValueError("sampled fixture result ID does not match its draw")
        return self


class TeamTableRow(BaseModel):
    """Immutable aggregate for one team."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: UUID
    played: StrictNonNegativeInt = 0
    won: StrictNonNegativeInt = 0
    drawn: StrictNonNegativeInt = 0
    lost: StrictNonNegativeInt = 0
    goals_for: StrictNonNegativeInt = 0
    goals_against: StrictNonNegativeInt = 0
    points: StrictNonNegativeInt = 0

    @model_validator(mode="after")
    def totals_must_agree(self) -> Self:
        if self.played != self.won + self.drawn + self.lost:
            raise ValueError("table appearances do not equal result totals")
        if self.points != 3 * self.won + self.drawn:
            raise ValueError("table points do not equal win and draw totals")
        return self

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


class LeagueTableState(BaseModel):
    """Canonical aggregate rows plus the ledger needed for head-to-head ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    team_ids: tuple[UUID, ...]
    matches: tuple[PlayedFixture, ...]
    rows: tuple[TeamTableRow, ...]

    @model_validator(mode="after")
    def table_shape_must_be_canonical(self) -> Self:
        if len(self.team_ids) != 20 or self.team_ids != tuple(
            sorted(set(self.team_ids), key=lambda value: value.int)
        ):
            raise ValueError("league table requires 20 unique ordered team IDs")
        if tuple(match.fixture_id for match in self.matches) != tuple(
            sorted(
                {match.fixture_id for match in self.matches},
                key=lambda value: value.int,
            )
        ):
            raise ValueError("table matches must have unique ordered fixture IDs")
        known = set(self.team_ids)
        if any(
            match.home_team_id not in known or match.away_team_id not in known
            for match in self.matches
        ):
            raise ValueError("table match references a non-member team")
        if tuple(row.team_id for row in self.rows) != self.team_ids:
            raise ValueError("table rows must follow the canonical team order")
        expected = {
            team_id: {
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "goals_for": 0,
                "goals_against": 0,
                "points": 0,
            }
            for team_id in self.team_ids
        }
        for match in self.matches:
            home = expected[match.home_team_id]
            away = expected[match.away_team_id]
            home["played"] += 1
            away["played"] += 1
            home["goals_for"] += match.scoreline.home_goals
            home["goals_against"] += match.scoreline.away_goals
            away["goals_for"] += match.scoreline.away_goals
            away["goals_against"] += match.scoreline.home_goals
            if match.scoreline.outcome == MatchOutcome.HOME_WIN:
                home["won"] += 1
                home["points"] += 3
                away["lost"] += 1
            elif match.scoreline.outcome == MatchOutcome.AWAY_WIN:
                away["won"] += 1
                away["points"] += 3
                home["lost"] += 1
            else:
                home["drawn"] += 1
                away["drawn"] += 1
                home["points"] += 1
                away["points"] += 1
        if any(
            row.model_dump(exclude={"team_id"}) != expected[row.team_id]
            for row in self.rows
        ):
            raise ValueError("table rows do not match the fixture ledger")
        return self


class RankedTableRow(TeamTableRow):
    """A fully resolved final-table row with disclosed head-to-head values."""

    position: Annotated[int, Field(strict=True, ge=1, le=20)]
    head_to_head_points: StrictNonNegativeInt = 0
    head_to_head_away_goals: StrictNonNegativeInt = 0


class RankedLeagueTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    rows: tuple[RankedTableRow, ...]

    @model_validator(mode="after")
    def positions_must_be_complete(self) -> Self:
        if len(self.rows) != 20 or tuple(row.position for row in self.rows) != tuple(
            range(1, 21)
        ):
            raise ValueError("ranked table must contain each position exactly once")
        if len({row.team_id for row in self.rows}) != 20:
            raise ValueError("ranked table team IDs must be unique")
        return self


class SeasonSimulationInput(BaseModel):
    """Canonical single-run input boundary used before vectorized execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_SCHEMA_VERSION
    competition_id: Literal["eng-premier-league"] = "eng-premier-league"
    season_id: SeasonId
    team_ids: tuple[UUID, ...]
    completed_matches: tuple[PlayedFixture, ...] = ()
    remaining_fixtures: tuple[SimulationFixture, ...] = ()

    @model_validator(mode="after")
    def season_input_must_be_canonical(self) -> Self:
        ordered_teams = tuple(sorted(set(self.team_ids), key=lambda value: value.int))
        if len(self.team_ids) != 20 or self.team_ids != ordered_teams:
            raise ValueError("simulation requires 20 unique ordered team IDs")
        completed_ids = tuple(match.fixture_id for match in self.completed_matches)
        if completed_ids != tuple(
            sorted(set(completed_ids), key=lambda value: value.int)
        ):
            raise ValueError("completed matches must have unique ordered fixture IDs")
        expected_remaining = tuple(
            fixture
            for batch in simulation_fixture_batches(self.remaining_fixtures)
            for fixture in batch.fixtures
        )
        remaining_ids = tuple(fixture.fixture_id for fixture in self.remaining_fixtures)
        if (
            self.remaining_fixtures != expected_remaining
            or len(remaining_ids) != len(set(remaining_ids))
            or set(completed_ids).intersection(remaining_ids)
        ):
            raise ValueError(
                "remaining fixtures are unordered or duplicate known fixtures"
            )
        known = set(self.team_ids)
        if any(
            match.home_team_id not in known or match.away_team_id not in known
            for match in self.completed_matches
        ) or any(
            fixture.season_id != self.season_id
            or fixture.home_team_id not in known
            or fixture.away_team_id not in known
            for fixture in self.remaining_fixtures
        ):
            raise ValueError("simulation fixture is outside the season membership")
        return self
