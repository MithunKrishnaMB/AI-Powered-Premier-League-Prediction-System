"""Versioned, model-ready training-example contracts."""

from datetime import UTC, datetime, time, timedelta
from typing import Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.features import PredictorSet, TrainingLabel
from pl_platform.domain.fixtures import KickoffPrecision

TRAINING_ROW_SCHEMA_VERSION: Final = 1
_PREMIER_LEAGUE_TIMEZONE = ZoneInfo("Europe/London")


def deterministic_training_example_id(
    feature_row_id: UUID,
    source_feature_dataset_id: str,
) -> UUID:
    """Return the stable identity for one model-ready training example."""

    identity = "|".join(
        (
            str(TRAINING_ROW_SCHEMA_VERSION),
            str(feature_row_id),
            source_feature_dataset_id,
        )
    )
    return uuid5(NAMESPACE_URL, f"pl-platform:training-example:{identity}")


class TrainingExample(BaseModel):
    """One fixture's approved predictors and structurally separate target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = TRAINING_ROW_SCHEMA_VERSION
    id: UUID
    feature_row_id: UUID
    fixture_id: UUID
    competition_id: Literal["eng-premier-league"]
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime
    kickoff_precision: KickoffPrecision
    feature_cutoff_at: datetime
    predictors: PredictorSet
    target: TrainingLabel
    source_feature_dataset_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def example_must_be_temporally_and_structurally_valid(self) -> Self:
        for field_name, value in (
            ("kickoff_at", self.kickoff_at),
            ("feature_cutoff_at", self.feature_cutoff_at),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                msg = f"{field_name} must be timezone-aware UTC"
                raise ValueError(msg)
        if self.home_team_id == self.away_team_id:
            msg = "home and away teams must differ"
            raise ValueError(msg)
        if not self.predictors.values:
            msg = "training examples require approved predictors"
            raise ValueError(msg)
        if self.kickoff_precision == KickoffPrecision.EXACT:
            if self.feature_cutoff_at > self.kickoff_at:
                msg = "feature cutoff cannot be later than an exact kickoff"
                raise ValueError(msg)
        else:
            local_date = self.kickoff_at.astimezone(_PREMIER_LEAGUE_TIMEZONE).date()
            local_start = datetime.combine(
                local_date,
                time.min,
                tzinfo=_PREMIER_LEAGUE_TIMEZONE,
            ).astimezone(UTC)
            if self.feature_cutoff_at >= local_start:
                msg = "date-only feature cutoff must precede its local fixture date"
                raise ValueError(msg)
        expected_id = deterministic_training_example_id(
            self.feature_row_id,
            self.source_feature_dataset_id,
        )
        if self.id != expected_id:
            msg = "training-example ID does not match its deterministic identity"
            raise ValueError(msg)
        return self
