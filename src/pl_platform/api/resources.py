"""Stable public schemas for read-only football and model resources."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResourceModel(BaseModel):
    """Strict immutable base for version-one resource contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FixtureStatus(StrEnum):
    """Persisted fixture states exposed by the API."""

    SCHEDULED = "scheduled"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class MatchOutcome(StrEnum):
    """Canonical three-way match outcome order."""

    HOME_WIN = "home_win"
    DRAW = "draw"
    AWAY_WIN = "away_win"


class RegistryState(StrEnum):
    """Persisted model-registry states, without promotion inference."""

    CANDIDATE = "candidate"
    DEVELOPMENT_ACCEPTED = "development_accepted"
    REJECTED = "rejected"
    ACTIVE = "active"
    RETIRED = "retired"


class Team(ResourceModel):
    """One canonical team name from a deterministic registry revision."""

    team_id: UUID
    slug: str
    display_name: str
    country_code: str
    registry_sha256: str


class SeasonTeam(ResourceModel):
    """One reviewed membership entry for a season."""

    ordinal: int = Field(ge=0)
    team: Team
    entry_status: Literal["continued", "promoted"]
    previous_competition_id: str | None


class Season(ResourceModel):
    """One canonical Premier League season registry entry."""

    competition_id: str
    season_id: str
    starts_on: date
    ends_on: date
    completed: bool
    registry_sha256: str
    team_count: int = Field(ge=0)


class SeasonDetail(Season):
    """A season plus its ordered, reviewed membership."""

    teams: tuple[SeasonTeam, ...]


class Fixture(ResourceModel):
    """Latest persisted fixture projection, preferring current evidence."""

    fixture_id: UUID
    competition_id: str
    season_id: str
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime | None
    kickoff_precision: Literal["exact", "date_only"] | None
    status: FixtureStatus | None
    matchweek: int | None = Field(default=None, ge=1)
    full_time_home_goals: int | None = Field(default=None, ge=0)
    full_time_away_goals: int | None = Field(default=None, ge=0)
    outcome: MatchOutcome | None


class StandingRow(ResourceModel):
    """One row in a complete persisted standings snapshot."""

    team: Team
    position: int = Field(ge=1, le=20)
    played: int = Field(ge=0)
    won: int = Field(ge=0)
    drawn: int = Field(ge=0)
    lost: int = Field(ge=0)
    goals_for: int = Field(ge=0)
    goals_against: int = Field(ge=0)
    goal_difference: int
    points: int = Field(ge=0)
    points_adjustment: int


class Standings(ResourceModel):
    """Latest complete standings snapshot for one season."""

    snapshot_id: UUID
    competition_id: str
    season_id: str
    retrieved_at: datetime
    rows: tuple[StandingRow, ...]


class Prediction(ResourceModel):
    """One immutable persisted three-way active-model prediction."""

    prediction_id: UUID
    fixture_id: UUID
    competition_id: str
    season_id: str
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime
    feature_cutoff_at: datetime
    model_id: UUID
    registry_entry_id: UUID
    registry_head_event_id: UUID
    method: str
    method_version: int = Field(ge=1)
    configuration_id: str
    home_win_probability: float = Field(ge=0.0, le=1.0)
    draw_probability: float = Field(ge=0.0, le=1.0)
    away_win_probability: float = Field(ge=0.0, le=1.0)


class Simulation(ResourceModel):
    """One complete persisted simulation run and summary identity."""

    simulation_id: UUID
    summary_id: UUID
    competition_id: str
    season_id: str
    algorithm_version: int = Field(ge=1)
    simulation_seed: int = Field(ge=0)
    simulation_count: int = Field(ge=1)


class PositionProbability(ResourceModel):
    """Persisted probability mass for one final league position."""

    position: int = Field(ge=1, le=20)
    probability: float = Field(ge=0.0, le=1.0)


class PredictedTableRow(ResourceModel):
    """Stored simulation summary ranked by deterministic expected values."""

    predicted_position: int = Field(ge=1, le=20)
    team: Team
    expected_points: float
    expected_goals_for: float
    expected_goals_against: float
    expected_goal_difference: float
    champion_probability: float = Field(ge=0.0, le=1.0)
    top_four_probability: float = Field(ge=0.0, le=1.0)
    top_six_probability: float = Field(ge=0.0, le=1.0)
    relegation_probability: float = Field(ge=0.0, le=1.0)
    position_probabilities: tuple[PositionProbability, ...]


class PredictedTable(ResourceModel):
    """Read-only ranking of one already-persisted simulation summary."""

    simulation: Simulation
    rows: tuple[PredictedTableRow, ...]


class ModelPerformance(ResourceModel):
    """Model identity, assessment and truthful current registry state."""

    model_id: UUID
    competition_id: str
    specification_version: int = Field(ge=1)
    selected_method: str
    selected_configuration_id: str
    selected_calibration: str
    assessment_accepted: bool
    registry_state: RegistryState | None
    evidence_scope: Literal["development"] = "development"


class EvaluationMetric(ResourceModel):
    """One persisted development-only probabilistic evaluation metric."""

    evaluation_dataset_id: str
    evaluation_manifest_sha256: str
    partition_id: str | None
    method: str
    configuration_id: str | None
    metric_scope: Literal["partition", "aggregate", "paired_calibration"]
    prediction_count: int = Field(gt=0)
    home_win_count: int = Field(ge=0)
    draw_count: int = Field(ge=0)
    away_win_count: int = Field(ge=0)
    mean_log_loss: float = Field(ge=0.0)
    mean_multiclass_brier_score: float = Field(ge=0.0)
    mean_ranked_probability_score: float = Field(ge=0.0)


class ModelPerformanceDetail(ModelPerformance):
    """Model performance with persisted development evaluation evidence."""

    metrics: tuple[EvaluationMetric, ...]
