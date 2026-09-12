"""Versioned, provider-independent point-in-time feature-row contracts."""

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome

FEATURE_ROW_SCHEMA_VERSION: Final = 1

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")]
PositiveVersion = Annotated[int, Field(strict=True, ge=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PredictorScalar = StrictBool | StrictInt | FiniteFloat | None

_RESERVED_PREDICTOR_NAMES = frozenset(
    {
        "away_goals",
        "full_time_away_goals",
        "full_time_home_goals",
        "home_goals",
        "outcome",
        "training_label",
    }
)
_RESERVED_PREDICTOR_PREFIXES = ("full_time_", "label_", "post_match_")
_PREMIER_LEAGUE_TIMEZONE = ZoneInfo("Europe/London")


def _must_be_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        msg = f"{field_name} must be timezone-aware UTC"
        raise ValueError(msg)


class PredictorValue(BaseModel):
    """One explicitly named pre-match value in a versioned predictor schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    value: PredictorScalar

    @field_validator("name")
    @classmethod
    def name_must_not_claim_post_match_data(cls, value: str) -> str:
        if value in _RESERVED_PREDICTOR_NAMES or value.startswith(
            _RESERVED_PREDICTOR_PREFIXES
        ):
            msg = f"predictor name {value!r} is reserved for post-match labels"
            raise ValueError(msg)
        return value


class PredictorSet(BaseModel):
    """Deterministically ordered values governed by an explicit feature schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Identifier
    schema_version: PositiveVersion
    values: tuple[PredictorValue, ...] = ()

    @model_validator(mode="after")
    def predictor_names_must_be_unique_and_ordered(self) -> Self:
        names = tuple(item.name for item in self.values)
        if len(names) != len(set(names)):
            msg = "predictor names must be unique"
            raise ValueError(msg)
        if names != tuple(sorted(names)):
            msg = "predictors must be ordered by name"
            raise ValueError(msg)
        return self


class TrainingLabel(BaseModel):
    """Post-match targets kept outside the pre-match predictor structure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: MatchOutcome
    home_goals: NonNegativeInt
    away_goals: NonNegativeInt

    @model_validator(mode="after")
    def outcome_must_match_score(self) -> Self:
        expected = MatchOutcome.DRAW
        if self.home_goals > self.away_goals:
            expected = MatchOutcome.HOME_WIN
        elif self.home_goals < self.away_goals:
            expected = MatchOutcome.AWAY_WIN
        if self.outcome != expected:
            msg = "training-label outcome does not match the final score"
            raise ValueError(msg)
        return self


class SourceArtifactProvenance(BaseModel):
    """Identity and integrity metadata for the verified upstream artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Identifier
    artifact_id: Identifier
    sha256: Sha256
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def capture_time_must_be_utc(cls, value: datetime) -> datetime:
        _must_be_utc(value, "captured_at")
        return value


class CanonicalDatasetProvenance(BaseModel):
    """Lineage of the manifest-verified canonical fixture dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: Identifier
    dataset_schema_version: PositiveVersion
    competition_id: Identifier
    season_id: Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")]
    fixtures_sha256: Sha256
    team_registry_schema_version: PositiveVersion
    season_registry_schema_version: PositiveVersion
    source: SourceArtifactProvenance


def deterministic_feature_row_id(
    *,
    fixture_id: UUID,
    feature_cutoff_at: datetime,
    predictor_schema_id: str,
    predictor_schema_version: int,
    canonical_dataset_id: str,
    canonical_fixtures_sha256: str,
) -> UUID:
    """Return the stable identity of one feature row and its input lineage."""

    _must_be_utc(feature_cutoff_at, "feature_cutoff_at")
    identity = "|".join(
        (
            str(FEATURE_ROW_SCHEMA_VERSION),
            str(fixture_id),
            feature_cutoff_at.isoformat(),
            predictor_schema_id,
            str(predictor_schema_version),
            canonical_dataset_id,
            canonical_fixtures_sha256,
        )
    )
    return uuid5(NAMESPACE_URL, f"pl-platform:feature-row:{identity}")


class PointInTimeFeatureRow(BaseModel):
    """One fixture's versioned predictors as known at a safe pre-match cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = FEATURE_ROW_SCHEMA_VERSION
    id: UUID
    fixture_id: UUID
    competition_id: Identifier
    season_id: Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")]
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime
    kickoff_precision: KickoffPrecision
    feature_cutoff_at: datetime
    predictors: PredictorSet
    training_label: TrainingLabel | None = None
    provenance: CanonicalDatasetProvenance

    @model_validator(mode="after")
    def row_must_be_internally_consistent(self) -> Self:
        _must_be_utc(self.kickoff_at, "kickoff_at")
        _must_be_utc(self.feature_cutoff_at, "feature_cutoff_at")

        if self.home_team_id == self.away_team_id:
            msg = "home and away teams must differ"
            raise ValueError(msg)
        if self.provenance.competition_id != self.competition_id:
            msg = "provenance competition does not match the feature row"
            raise ValueError(msg)
        if self.provenance.season_id != self.season_id:
            msg = "provenance season does not match the feature row"
            raise ValueError(msg)

        if self.kickoff_precision == KickoffPrecision.EXACT:
            if self.feature_cutoff_at > self.kickoff_at:
                msg = "feature cutoff cannot be later than an exact kickoff"
                raise ValueError(msg)
        else:
            if self.competition_id != "eng-premier-league":
                msg = "date-only cutoff validation requires a known competition"
                raise ValueError(msg)
            local_fixture_date = self.kickoff_at.astimezone(
                _PREMIER_LEAGUE_TIMEZONE
            ).date()
            local_date_start = datetime.combine(
                local_fixture_date,
                time.min,
                tzinfo=_PREMIER_LEAGUE_TIMEZONE,
            ).astimezone(UTC)
            if self.feature_cutoff_at >= local_date_start:
                msg = (
                    "date-only fixtures require a cutoff before the source-local "
                    "fixture date"
                )
                raise ValueError(msg)

        expected_id = deterministic_feature_row_id(
            fixture_id=self.fixture_id,
            feature_cutoff_at=self.feature_cutoff_at,
            predictor_schema_id=self.predictors.schema_id,
            predictor_schema_version=self.predictors.schema_version,
            canonical_dataset_id=self.provenance.dataset_id,
            canonical_fixtures_sha256=self.provenance.fixtures_sha256,
        )
        if self.id != expected_id:
            msg = "feature-row ID does not match its deterministic identity"
            raise ValueError(msg)
        return self
