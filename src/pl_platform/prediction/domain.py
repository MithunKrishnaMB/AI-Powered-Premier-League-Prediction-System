"""Strict contracts for the current-season prediction lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from math import fsum, isclose, log
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.domain.features import PredictorSet
from pl_platform.domain.fixtures import Fixture, FixtureStatus, MatchOutcome
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes

UPCOMING_FEATURE_SCHEMA_VERSION: Final = 1
CURRENT_PREDICTION_SCHEMA_VERSION: Final = 1
COMPLETED_EVALUATION_SCHEMA_VERSION: Final = 1
SEALED_TEST_SEASON_ID: Final = "2025-2026"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
BatchKind = Literal["exact_kickoff", "date_only_date"]
_PREMIER_LEAGUE_TIMEZONE: Final = ZoneInfo("Europe/London")


class PredictionLifecycleFailureCode(StrEnum):
    """Stable failure categories for the three implemented lifecycle steps."""

    INVALID_FEATURE_INPUT = "invalid_feature_input"
    CHRONOLOGY_VIOLATION = "chronology_violation"
    PREDICTOR_SCHEMA_INCOMPATIBLE = "predictor_schema_incompatible"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    SEALED_TARGET_PROHIBITED = "sealed_target_prohibited"
    ACTIVE_MODEL_REQUIRED = "active_model_required"
    PREDICTION_FAILED = "prediction_failed"
    RESULT_MISMATCH = "result_mismatch"
    ZERO_ACTUAL_PROBABILITY = "zero_actual_probability"


class PredictionLifecycleError(ValueError):
    """A lifecycle input would violate chronology, lineage or model policy."""

    def __init__(
        self, code: PredictionLifecycleFailureCode | str, message: str
    ) -> None:
        self.code = code
        value = code.value if isinstance(code, PredictionLifecycleFailureCode) else code
        super().__init__(f"{value}: {message}")


class CurrentFixtureEvidence(BaseModel):
    """Exact synchronized current-fixture evidence used for one feature row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture: Fixture
    revision_id: UUID
    revision_identity_sha256: Sha256
    observation_id: UUID
    cache_key_sha256: Sha256
    retrieved_at: datetime
    batch_id: UUID
    batch_identity_sha256: Sha256
    batch_kind: BatchKind
    batch_member_ordinal: Annotated[int, Field(strict=True, ge=0)]
    knowledge_available_at: datetime

    @field_validator("retrieved_at", "knowledge_available_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("current fixture evidence timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def evidence_must_describe_an_upcoming_fixture(self) -> Self:
        if self.fixture.status is not FixtureStatus.SCHEDULED:
            raise ValueError("upcoming feature evidence requires a scheduled fixture")
        if self.retrieved_at > self.knowledge_available_at:
            raise ValueError("fixture retrieval cannot follow its knowledge boundary")
        if (
            self.fixture.kickoff_precision == "date_only"
            and self.batch_kind != "date_only_date"
        ):
            raise ValueError("date-only fixtures require a whole-date batch")
        if self.fixture.kickoff_precision == "date_only":
            local_date = self.fixture.kickoff_at.astimezone(
                _PREMIER_LEAGUE_TIMEZONE
            ).date()
            local_start = datetime.combine(
                local_date, time.min, tzinfo=_PREMIER_LEAGUE_TIMEZONE
            ).astimezone(UTC)
            if self.knowledge_available_at >= local_start:
                raise ValueError(
                    "date-only fixture knowledge must precede its local date"
                )
        return self


class CompletedResultEvidence(BaseModel):
    """One official completed result available to pre-match state replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture: Fixture
    result_id: UUID
    result_identity_sha256: Sha256
    observation_id: UUID
    cache_key_sha256: Sha256
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def retrieval_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("completed-result retrieval must be UTC")
        return value

    @model_validator(mode="after")
    def evidence_must_describe_a_completed_result(self) -> Self:
        if (
            self.fixture.status is not FixtureStatus.FINISHED
            or self.fixture.full_time_score is None
            or self.fixture.outcome is None
        ):
            raise ValueError("completed-result evidence requires an official result")
        return self


def _predictor_payload_sha256(predictors: PredictorSet) -> str:
    return sha256_bytes(canonical_json_bytes(predictors))


def _upcoming_feature_identity_payload(
    *,
    fixture_evidence: CurrentFixtureEvidence,
    feature_cutoff_at: datetime,
    predictors: PredictorSet,
    completed_results: tuple[CompletedResultEvidence, ...],
    historical_context_sha256: str,
    opening_priors_sha256: str,
    initial_elo_sha256: str,
) -> dict[str, object]:
    return {
        "batch_id": str(fixture_evidence.batch_id),
        "batch_identity_sha256": fixture_evidence.batch_identity_sha256,
        "completed_results": [
            {
                "cache_key_sha256": result.cache_key_sha256,
                "observation_id": str(result.observation_id),
                "result_id": str(result.result_id),
                "result_identity_sha256": result.result_identity_sha256,
                "retrieved_at": result.retrieved_at.isoformat(),
            }
            for result in completed_results
        ],
        "feature_cutoff_at": feature_cutoff_at.isoformat(),
        "fixture_id": str(fixture_evidence.fixture.id),
        "fixture_observation_id": str(fixture_evidence.observation_id),
        "fixture_revision_id": str(fixture_evidence.revision_id),
        "fixture_revision_identity_sha256": (fixture_evidence.revision_identity_sha256),
        "historical_context_sha256": historical_context_sha256,
        "initial_elo_sha256": initial_elo_sha256,
        "opening_priors_sha256": opening_priors_sha256,
        "predictor_payload_sha256": _predictor_payload_sha256(predictors),
        "predictor_schema_id": predictors.schema_id,
        "predictor_schema_version": predictors.schema_version,
        "schema_version": UPCOMING_FEATURE_SCHEMA_VERSION,
    }


def upcoming_feature_identity(
    *,
    fixture_evidence: CurrentFixtureEvidence,
    feature_cutoff_at: datetime,
    predictors: PredictorSet,
    completed_results: tuple[CompletedResultEvidence, ...],
    historical_context_sha256: str,
    opening_priors_sha256: str,
    initial_elo_sha256: str,
) -> tuple[UUID, str, bytes]:
    """Return the deterministic ID, checksum and canonical identity bytes."""

    payload = canonical_json_bytes(
        _upcoming_feature_identity_payload(
            fixture_evidence=fixture_evidence,
            feature_cutoff_at=feature_cutoff_at,
            predictors=predictors,
            completed_results=completed_results,
            historical_context_sha256=historical_context_sha256,
            opening_priors_sha256=opening_priors_sha256,
            initial_elo_sha256=initial_elo_sha256,
        )
    )
    checksum = sha256_bytes(payload)
    identity = uuid5(
        NAMESPACE_URL,
        f"pl-platform:upcoming-feature:{UPCOMING_FEATURE_SCHEMA_VERSION}|{checksum}",
    )
    return identity, checksum, payload


class UpcomingFeatureRow(BaseModel):
    """Unlabelled schema-v2 predictors with complete current-state provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = UPCOMING_FEATURE_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    fixture_evidence: CurrentFixtureEvidence
    fixture_id: UUID
    competition_id: Literal["eng-premier-league"]
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime
    feature_cutoff_at: datetime
    predictors: PredictorSet
    predictor_payload_sha256: Sha256
    completed_results: tuple[CompletedResultEvidence, ...]
    historical_context_sha256: Sha256
    opening_priors_sha256: Sha256
    initial_elo_sha256: Sha256

    @field_validator("kickoff_at", "feature_cutoff_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("upcoming feature timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def row_must_match_its_inputs_and_identity(self) -> Self:
        fixture = self.fixture_evidence.fixture
        if self.season_id == SEALED_TEST_SEASON_ID:
            raise ValueError("sealed 2025-2026 targets cannot enter current features")
        if (
            fixture.id != self.fixture_id
            or fixture.competition_id != self.competition_id
            or fixture.season_id != self.season_id
            or fixture.home_team_id != self.home_team_id
            or fixture.away_team_id != self.away_team_id
            or fixture.kickoff_at != self.kickoff_at
        ):
            raise ValueError("upcoming feature snapshot disagrees with its fixture")
        if self.feature_cutoff_at != self.fixture_evidence.knowledge_available_at:
            raise ValueError(
                "feature cutoff must equal the evidence knowledge boundary"
            )
        if self.feature_cutoff_at >= self.kickoff_at:
            raise ValueError("upcoming features require a strictly pre-kickoff cutoff")
        if self.predictor_payload_sha256 != _predictor_payload_sha256(self.predictors):
            raise ValueError("predictor payload checksum does not match")
        ordered_results = tuple(
            sorted(
                self.completed_results,
                key=lambda item: (item.fixture.kickoff_at, item.fixture.id),
            )
        )
        if self.completed_results != ordered_results:
            raise ValueError("completed-result provenance must be canonical")
        if len({item.fixture.id for item in ordered_results}) != len(ordered_results):
            raise ValueError("completed-result provenance repeats a fixture")
        if any(item.retrieved_at > self.feature_cutoff_at for item in ordered_results):
            raise ValueError("feature state contains a result learned after its cutoff")
        expected_id, expected_sha256, _ = upcoming_feature_identity(
            fixture_evidence=self.fixture_evidence,
            feature_cutoff_at=self.feature_cutoff_at,
            predictors=self.predictors,
            completed_results=self.completed_results,
            historical_context_sha256=self.historical_context_sha256,
            opening_priors_sha256=self.opening_priors_sha256,
            initial_elo_sha256=self.initial_elo_sha256,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("upcoming feature identity does not match its lineage")
        return self


def current_prediction_identity(
    *,
    feature_id: UUID,
    feature_identity_sha256: str,
    registry_entry_id: UUID,
    registry_head_event_id: UUID,
    registry_head_event_sha256: str,
    model_id: UUID,
    artifact_id: UUID,
    manifest_id: UUID,
    artifact_manifest_sha256: str,
    configuration_id: str,
) -> tuple[UUID, str, bytes]:
    payload = canonical_json_bytes(
        {
            "artifact_id": str(artifact_id),
            "artifact_manifest_sha256": artifact_manifest_sha256,
            "configuration_id": configuration_id,
            "feature_id": str(feature_id),
            "feature_identity_sha256": feature_identity_sha256,
            "manifest_id": str(manifest_id),
            "method": "catboost",
            "method_version": 1,
            "model_id": str(model_id),
            "registry_entry_id": str(registry_entry_id),
            "registry_head_event_id": str(registry_head_event_id),
            "registry_head_event_sha256": registry_head_event_sha256,
            "schema_version": CURRENT_PREDICTION_SCHEMA_VERSION,
        }
    )
    checksum = sha256_bytes(payload)
    identity = uuid5(
        NAMESPACE_URL,
        f"pl-platform:current-prediction:{CURRENT_PREDICTION_SCHEMA_VERSION}|{checksum}",
    )
    return identity, checksum, payload


class CurrentModelPrediction(BaseModel):
    """One immutable target-free prediction from an explicitly active model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = CURRENT_PREDICTION_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    feature_id: UUID
    feature_identity_sha256: Sha256
    fixture_id: UUID
    competition_id: Literal["eng-premier-league"]
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    home_team_id: UUID
    away_team_id: UUID
    kickoff_at: datetime
    feature_cutoff_at: datetime
    registry_entry_id: UUID
    registry_head_event_id: UUID
    registry_head_event_sha256: Sha256
    model_id: UUID
    artifact_id: UUID
    manifest_id: UUID
    artifact_manifest_sha256: Sha256
    method: Literal["catboost"] = "catboost"
    method_version: Literal[1] = 1
    configuration_id: Literal["catboost-depth6-regularized"]
    probabilities: OutcomeProbabilities

    @field_validator("kickoff_at", "feature_cutoff_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("current prediction timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def prediction_must_be_pre_match_and_target_free(self) -> Self:
        if self.season_id == SEALED_TEST_SEASON_ID:
            raise ValueError("sealed 2025-2026 fixtures cannot be predicted")
        if self.feature_cutoff_at >= self.kickoff_at:
            raise ValueError("current prediction must use pre-kickoff features")
        expected_id, expected_sha256, _ = current_prediction_identity(
            feature_id=self.feature_id,
            feature_identity_sha256=self.feature_identity_sha256,
            registry_entry_id=self.registry_entry_id,
            registry_head_event_id=self.registry_head_event_id,
            registry_head_event_sha256=self.registry_head_event_sha256,
            model_id=self.model_id,
            artifact_id=self.artifact_id,
            manifest_id=self.manifest_id,
            artifact_manifest_sha256=self.artifact_manifest_sha256,
            configuration_id=self.configuration_id,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("current prediction identity does not match its lineage")
        return self


def completed_evaluation_identity(
    *,
    prediction_id: UUID,
    prediction_identity_sha256: str,
    result_id: UUID,
    result_identity_sha256: str,
    result_observation_id: UUID,
    result_cache_key_sha256: str,
    result_retrieved_at: datetime,
) -> tuple[UUID, str, bytes]:
    payload = canonical_json_bytes(
        {
            "prediction_id": str(prediction_id),
            "prediction_identity_sha256": prediction_identity_sha256,
            "result_cache_key_sha256": result_cache_key_sha256,
            "result_id": str(result_id),
            "result_identity_sha256": result_identity_sha256,
            "result_observation_id": str(result_observation_id),
            "result_retrieved_at": result_retrieved_at.isoformat(),
            "schema_version": COMPLETED_EVALUATION_SCHEMA_VERSION,
        }
    )
    checksum = sha256_bytes(payload)
    identity = uuid5(
        NAMESPACE_URL,
        "pl-platform:completed-prediction-evaluation:"
        f"{COMPLETED_EVALUATION_SCHEMA_VERSION}|{checksum}",
    )
    return identity, checksum, payload


class CompletedPredictionEvaluation(BaseModel):
    """Immutable per-fixture probabilistic scores after an official result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = COMPLETED_EVALUATION_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    prediction_id: UUID
    prediction_identity_sha256: Sha256
    result_id: UUID
    result_identity_sha256: Sha256
    result_observation_id: UUID
    result_cache_key_sha256: Sha256
    result_retrieved_at: datetime
    fixture_id: UUID
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    outcome: MatchOutcome
    probabilities: OutcomeProbabilities
    actual_outcome_probability: Annotated[
        float, Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False)
    ]
    log_loss: NonNegativeFloat
    multiclass_brier_score: NonNegativeFloat
    ranked_probability_score: NonNegativeFloat

    @field_validator("result_retrieved_at")
    @classmethod
    def result_retrieval_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("completed evaluation result retrieval must be UTC")
        return value

    @model_validator(mode="after")
    def evaluation_must_be_finite_and_current(self) -> Self:
        if self.season_id == SEALED_TEST_SEASON_ID:
            raise ValueError("sealed 2025-2026 outcomes cannot be evaluated")
        expected_id, expected_sha256, _ = completed_evaluation_identity(
            prediction_id=self.prediction_id,
            prediction_identity_sha256=self.prediction_identity_sha256,
            result_id=self.result_id,
            result_identity_sha256=self.result_identity_sha256,
            result_observation_id=self.result_observation_id,
            result_cache_key_sha256=self.result_cache_key_sha256,
            result_retrieved_at=self.result_retrieved_at,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("completed evaluation identity does not match its lineage")
        actual_probability = self.probabilities.for_outcome(self.outcome)
        if not isclose(
            self.actual_outcome_probability,
            actual_probability,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("completed evaluation actual probability does not match")
        ordered_probabilities = (
            self.probabilities.home_win,
            self.probabilities.draw,
            self.probabilities.away_win,
        )
        outcome_index = {
            MatchOutcome.HOME_WIN: 0,
            MatchOutcome.DRAW: 1,
            MatchOutcome.AWAY_WIN: 2,
        }[self.outcome]
        observations = tuple(
            1.0 if index == outcome_index else 0.0 for index in range(3)
        )
        expected_brier = fsum(
            (probability - observation) ** 2
            for probability, observation in zip(
                ordered_probabilities, observations, strict=True
            )
        )
        expected_ranked = (
            fsum(
                (fsum(ordered_probabilities[:boundary]) - fsum(observations[:boundary]))
                ** 2
                for boundary in (1, 2)
            )
            / 2.0
        )
        expected = (-log(actual_probability), expected_brier, expected_ranked)
        actual = (
            self.log_loss,
            self.multiclass_brier_score,
            self.ranked_probability_score,
        )
        if any(
            not isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(actual, expected, strict=True)
        ):
            raise ValueError("completed evaluation metric values do not match")
        return self
