"""Typed contracts for deterministic probabilistic model evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isclose
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.fixtures import MatchOutcome

EVALUATION_SCHEMA_VERSION: Final = 1
OUTCOME_ORDER: Final = (
    MatchOutcome.HOME_WIN,
    MatchOutcome.DRAW,
    MatchOutcome.AWAY_WIN,
)

Probability = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
SeasonId = Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
EvaluationMethod = Literal["naive", "elo", "multinomial_logistic"]


class EvaluationContractError(ValueError):
    """Evaluation inputs violate a chronological or probabilistic contract."""


class ChronologicalEvaluationWindow(BaseModel):
    """An explicit season-level reference and evaluation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    reference_season_ids: tuple[SeasonId, ...] = Field(min_length=1)
    evaluation_season_ids: tuple[SeasonId, ...] = Field(min_length=1)
    excluded_season_ids: tuple[SeasonId, ...] = ()

    @model_validator(mode="after")
    def seasons_must_be_unique_ordered_and_chronological(self) -> Self:
        groups = (
            self.reference_season_ids,
            self.evaluation_season_ids,
            self.excluded_season_ids,
        )
        for seasons in groups:
            if seasons != tuple(sorted(set(seasons))):
                msg = "season groups must contain unique ordered season IDs"
                raise ValueError(msg)
        all_seasons = tuple(season for group in groups for season in group)
        if len(all_seasons) != len(set(all_seasons)):
            msg = "reference, evaluation and excluded seasons must be disjoint"
            raise ValueError(msg)
        if self.reference_season_ids[-1] >= self.evaluation_season_ids[0]:
            msg = "reference seasons must precede evaluation seasons"
            raise ValueError(msg)
        if (
            self.excluded_season_ids
            and self.evaluation_season_ids[-1] >= self.excluded_season_ids[0]
        ):
            msg = "evaluation seasons must precede excluded seasons"
            raise ValueError(msg)
        return self


class OutcomeProbabilities(BaseModel):
    """Three-way Premier League full-time-result probabilities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_win: Probability
    draw: Probability
    away_win: Probability

    @model_validator(mode="after")
    def probabilities_must_sum_to_one(self) -> Self:
        if not isclose(
            self.home_win + self.draw + self.away_win,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            msg = "outcome probabilities must sum to one"
            raise ValueError(msg)
        return self

    def for_outcome(self, outcome: MatchOutcome) -> float:
        """Return the probability assigned to one canonical outcome."""

        if outcome == MatchOutcome.HOME_WIN:
            return self.home_win
        if outcome == MatchOutcome.DRAW:
            return self.draw
        return self.away_win


def deterministic_prediction_id(
    *,
    source_training_sha256: str,
    source_training_example_id: UUID,
    partition_id: str,
    method: EvaluationMethod,
    method_version: int,
) -> UUID:
    """Return a stable prediction identity bound to input data and method."""

    identity = "|".join(
        (
            str(EVALUATION_SCHEMA_VERSION),
            source_training_sha256,
            str(source_training_example_id),
            partition_id,
            method,
            str(method_version),
        )
    )
    return uuid5(NAMESPACE_URL, f"pl-platform:evaluation-prediction:{identity}")


class ProbabilisticPrediction(BaseModel):
    """A target-free prediction made from one point-in-time example."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = EVALUATION_SCHEMA_VERSION
    id: UUID
    method: EvaluationMethod
    method_version: Literal[1]
    partition_id: str = Field(min_length=1)
    source_training_dataset_id: str = Field(min_length=1)
    source_training_sha256: Sha256
    source_training_example_id: UUID
    fixture_id: UUID
    season_id: SeasonId
    kickoff_at: datetime
    feature_cutoff_at: datetime
    probabilities: OutcomeProbabilities

    @field_validator("kickoff_at", "feature_cutoff_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            msg = "prediction timestamps must be timezone-aware UTC"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def identity_must_match_prediction(self) -> Self:
        expected = deterministic_prediction_id(
            source_training_sha256=self.source_training_sha256,
            source_training_example_id=self.source_training_example_id,
            partition_id=self.partition_id,
            method=self.method,
            method_version=self.method_version,
        )
        if self.id != expected:
            msg = "prediction ID does not match its deterministic identity"
            raise ValueError(msg)
        if self.feature_cutoff_at > self.kickoff_at:
            msg = "prediction cutoff cannot follow kickoff"
            raise ValueError(msg)
        return self


class OutcomeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    home_win: Annotated[int, Field(strict=True, ge=0)]
    draw: Annotated[int, Field(strict=True, ge=0)]
    away_win: Annotated[int, Field(strict=True, ge=0)]

    @property
    def total(self) -> int:
        return self.home_win + self.draw + self.away_win


class ProbabilisticMetricSummary(BaseModel):
    """Strictly probabilistic scores for one method and partition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: EvaluationMethod
    prediction_count: PositiveInt
    outcome_counts: OutcomeCounts
    mean_log_loss: NonNegativeFloat
    mean_multiclass_brier_score: NonNegativeFloat
    mean_ranked_probability_score: NonNegativeFloat

    @model_validator(mode="after")
    def counts_must_agree(self) -> Self:
        if self.outcome_counts.total != self.prediction_count:
            msg = "outcome counts must equal prediction count"
            raise ValueError(msg)
        return self
