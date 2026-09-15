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
TEAM_STATE_SCHEMA_VERSION: Final = 1
PREDICTION_REGENERATION_SCHEMA_VERSION: Final = 1
SIMULATION_REGENERATION_SCHEMA_VERSION: Final = 1
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
    STATE_CHAIN_INVALID = "state_chain_invalid"
    RESULT_ALREADY_APPLIED = "result_already_applied"
    REGENERATION_NOT_REQUIRED = "regeneration_not_required"
    SCORELINE_PROVENANCE_REQUIRED = "scoreline_provenance_required"
    SIMULATION_FAILED = "simulation_failed"


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


def _identified_payload(
    namespace: str,
    schema_version: int,
    payload: dict[str, object],
) -> tuple[UUID, str, bytes]:
    exact = canonical_json_bytes(payload)
    checksum = sha256_bytes(exact)
    identity = uuid5(
        NAMESPACE_URL,
        f"pl-platform:{namespace}:{schema_version}|{checksum}",
    )
    return identity, checksum, exact


class TeamEloRating(BaseModel):
    """One canonical team's finite Elo value in an operational state snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: UUID
    rating: Annotated[float, Field(strict=True, allow_inf_nan=False)]


def team_state_identity(
    *,
    season_id: str,
    initial_elo_sha256: str,
    completed_results: tuple[CompletedResultEvidence, ...],
    elo_ratings: tuple[TeamEloRating, ...],
) -> tuple[UUID, str, bytes]:
    return _identified_payload(
        "operational-team-state",
        TEAM_STATE_SCHEMA_VERSION,
        {
            "completed_results": [
                result.model_dump(mode="json") for result in completed_results
            ],
            "elo_ratings": [rating.model_dump(mode="json") for rating in elo_ratings],
            "initial_elo_sha256": initial_elo_sha256,
            "schema_version": TEAM_STATE_SCHEMA_VERSION,
            "season_id": season_id,
        },
    )


class OperationalTeamState(BaseModel):
    """Append-only result ledger and Elo state used by future feature builds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = TEAM_STATE_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    initial_elo_sha256: Sha256
    completed_results: tuple[CompletedResultEvidence, ...]
    elo_ratings: tuple[TeamEloRating, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def state_must_be_canonical(self) -> Self:
        if self.season_id == SEALED_TEST_SEASON_ID:
            raise ValueError("sealed 2025-2026 results cannot enter operational state")
        if tuple(item.team_id for item in self.elo_ratings) != tuple(
            sorted({item.team_id for item in self.elo_ratings})
        ):
            raise ValueError("team-state Elo ratings must be unique and ordered")
        ordered_results = tuple(
            sorted(
                self.completed_results,
                key=lambda item: (item.fixture.kickoff_at, item.fixture.id),
            )
        )
        if self.completed_results != ordered_results or len(
            {item.result_id for item in ordered_results}
        ) != len(ordered_results):
            raise ValueError("team-state results must be unique and ordered")
        if any(item.fixture.season_id != self.season_id for item in ordered_results):
            raise ValueError("team-state result has a different season")
        expected_id, expected_sha256, _ = team_state_identity(
            season_id=self.season_id,
            initial_elo_sha256=self.initial_elo_sha256,
            completed_results=self.completed_results,
            elo_ratings=self.elo_ratings,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("team-state identity does not match its contents")
        return self


class AppliedPredictionResult(BaseModel):
    """One evaluation/result pair applied in a simultaneous state batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation: CompletedPredictionEvaluation
    result: CompletedResultEvidence

    @model_validator(mode="after")
    def evaluation_and_result_must_match(self) -> Self:
        if (
            self.evaluation.result_id != self.result.result_id
            or self.evaluation.result_identity_sha256
            != self.result.result_identity_sha256
            or self.evaluation.result_observation_id != self.result.observation_id
            or self.evaluation.result_cache_key_sha256 != self.result.cache_key_sha256
            or self.evaluation.result_retrieved_at != self.result.retrieved_at
            or self.evaluation.fixture_id != self.result.fixture.id
        ):
            raise ValueError("applied evaluation and result evidence disagree")
        return self


def team_state_advancement_identity(
    *,
    prior_advancement_id: UUID | None,
    pre_state: OperationalTeamState,
    post_state: OperationalTeamState,
    applied_results: tuple[AppliedPredictionResult, ...],
) -> tuple[UUID, str, bytes]:
    return _identified_payload(
        "team-state-advancement",
        TEAM_STATE_SCHEMA_VERSION,
        {
            "applied_results": [
                {
                    "evaluation_id": str(item.evaluation.id),
                    "evaluation_identity_sha256": item.evaluation.identity_sha256,
                    "result_id": str(item.result.result_id),
                    "result_identity_sha256": item.result.result_identity_sha256,
                }
                for item in applied_results
            ],
            "post_state_id": str(post_state.id),
            "post_state_sha256": post_state.identity_sha256,
            "pre_state_id": str(pre_state.id),
            "pre_state_sha256": pre_state.identity_sha256,
            "prior_advancement_id": (
                None if prior_advancement_id is None else str(prior_advancement_id)
            ),
            "schema_version": TEAM_STATE_SCHEMA_VERSION,
            "season_id": post_state.season_id,
        },
    )


class TeamStateAdvancement(BaseModel):
    """One immutable, exactly-once simultaneous result-batch advancement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = TEAM_STATE_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    prior_advancement_id: UUID | None = None
    pre_state: OperationalTeamState
    post_state: OperationalTeamState
    applied_results: tuple[AppliedPredictionResult, ...] = Field(min_length=1)
    applied_at: datetime

    @field_validator("applied_at")
    @classmethod
    def applied_time_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("state advancement timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def advancement_must_match_states(self) -> Self:
        if self.pre_state.season_id != self.post_state.season_id:
            raise ValueError("state advancement cannot cross seasons")
        if self.applied_at != max(
            item.result.retrieved_at for item in self.applied_results
        ):
            raise ValueError("state advancement time must match result evidence")
        if len({item.result.result_id for item in self.applied_results}) != len(
            self.applied_results
        ):
            raise ValueError("state advancement repeats a result")
        expected_id, expected_sha256, _ = team_state_advancement_identity(
            prior_advancement_id=self.prior_advancement_id,
            pre_state=self.pre_state,
            post_state=self.post_state,
            applied_results=self.applied_results,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("state advancement identity does not match")
        return self


def prediction_regeneration_identity(
    *,
    advancement_id: UUID,
    advancement_identity_sha256: str,
    prior_prediction: CurrentModelPrediction,
    replacement_prediction: CurrentModelPrediction,
) -> tuple[UUID, str, bytes]:
    return _identified_payload(
        "prediction-regeneration",
        PREDICTION_REGENERATION_SCHEMA_VERSION,
        {
            "advancement_id": str(advancement_id),
            "advancement_identity_sha256": advancement_identity_sha256,
            "fixture_id": str(prior_prediction.fixture_id),
            "prior_prediction_id": str(prior_prediction.id),
            "prior_prediction_identity_sha256": prior_prediction.identity_sha256,
            "replacement_prediction_id": str(replacement_prediction.id),
            "replacement_prediction_identity_sha256": (
                replacement_prediction.identity_sha256
            ),
            "schema_version": PREDICTION_REGENERATION_SCHEMA_VERSION,
            "season_id": prior_prediction.season_id,
        },
    )


class PredictionRegeneration(BaseModel):
    """Immutable supersession lineage for one affected future prediction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = PREDICTION_REGENERATION_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    advancement_id: UUID
    advancement_identity_sha256: Sha256
    prior_feature: UpcomingFeatureRow
    prior_prediction: CurrentModelPrediction
    replacement_feature: UpcomingFeatureRow
    replacement_prediction: CurrentModelPrediction

    @model_validator(mode="after")
    def replacement_must_supersede_same_fixture(self) -> Self:
        old = self.prior_prediction
        new = self.replacement_prediction
        if (
            self.prior_feature.id != old.feature_id
            or self.replacement_feature.id != new.feature_id
            or old.fixture_id != new.fixture_id
            or old.season_id != new.season_id
            or new.feature_cutoff_at <= old.feature_cutoff_at
            or old.id == new.id
        ):
            raise ValueError("prediction regeneration does not supersede one fixture")
        expected_id, expected_sha256, _ = prediction_regeneration_identity(
            advancement_id=self.advancement_id,
            advancement_identity_sha256=self.advancement_identity_sha256,
            prior_prediction=old,
            replacement_prediction=new,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("prediction regeneration identity does not match")
        return self


def distribution_provenance_identity(
    *,
    distribution_id: UUID,
    input_sha256: str,
    producer_identity: str,
    producer_version: str,
    runtime_contract: str,
    numerical_contract: str,
    approval_context: str,
) -> tuple[UUID, str, bytes]:
    exact = canonical_json_bytes(
        {
            "approval_context": approval_context,
            "artifact_id": None,
            "distribution_id": str(distribution_id),
            "input_sha256": input_sha256,
            "numerical_contract": numerical_contract,
            "producer_identity": producer_identity,
            "producer_kind": "explicit_input",
            "producer_version": producer_version,
            "runtime_contract": runtime_contract,
            "schema_version": 1,
        }
    )
    checksum = sha256_bytes(exact)
    return (
        uuid5(NAMESPACE_URL, f"pl-platform:distribution-provenance:{checksum}"),
        checksum,
        exact,
    )


class ExplicitScorelineProvenance(BaseModel):
    """Approval for separately supplied scorelines; never classifier-derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    id: UUID
    identity_sha256: Sha256
    distribution_id: UUID
    input_sha256: Sha256
    producer_kind: Literal["explicit_input"] = "explicit_input"
    producer_identity: str = Field(min_length=1)
    producer_version: str = Field(min_length=1)
    runtime_contract: str = Field(min_length=1)
    numerical_contract: str = Field(min_length=1)
    approval_context: str = Field(min_length=1)

    @model_validator(mode="after")
    def provenance_identity_must_match(self) -> Self:
        expected_id, expected_sha256, _ = distribution_provenance_identity(
            distribution_id=self.distribution_id,
            input_sha256=self.input_sha256,
            producer_identity=self.producer_identity,
            producer_version=self.producer_version,
            runtime_contract=self.runtime_contract,
            numerical_contract=self.numerical_contract,
            approval_context=self.approval_context,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("scoreline provenance identity does not match")
        return self


def season_simulation_regeneration_identity(
    *,
    advancement_id: UUID,
    advancement_identity_sha256: str,
    previous_simulation_id: UUID,
    replacement_input_sha256: str,
    replacement_simulation_id: UUID,
    replacement_summary_id: UUID,
    simulation_seed: int,
    season_id: str,
) -> tuple[UUID, str, bytes]:
    return _identified_payload(
        "season-simulation-regeneration",
        SIMULATION_REGENERATION_SCHEMA_VERSION,
        {
            "advancement_id": str(advancement_id),
            "advancement_identity_sha256": advancement_identity_sha256,
            "previous_simulation_id": str(previous_simulation_id),
            "replacement_input_sha256": replacement_input_sha256,
            "replacement_simulation_id": str(replacement_simulation_id),
            "replacement_summary_id": str(replacement_summary_id),
            "schema_version": SIMULATION_REGENERATION_SCHEMA_VERSION,
            "season_id": season_id,
            "simulation_seed": simulation_seed,
        },
    )


class SeasonSimulationRegeneration(BaseModel):
    """Immutable lineage from a state advancement to a replacement simulation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SIMULATION_REGENERATION_SCHEMA_VERSION
    id: UUID
    identity_sha256: Sha256
    advancement_id: UUID
    advancement_identity_sha256: Sha256
    previous_simulation_id: UUID
    replacement_input_sha256: Sha256
    replacement_simulation_id: UUID
    replacement_summary_id: UUID
    simulation_seed: Annotated[int, Field(strict=True, ge=0, lt=2**64)]
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")

    @model_validator(mode="after")
    def regeneration_identity_must_match(self) -> Self:
        if self.season_id == SEALED_TEST_SEASON_ID:
            raise ValueError("sealed 2025-2026 simulations cannot be regenerated")
        if self.previous_simulation_id == self.replacement_simulation_id:
            raise ValueError("replacement simulation must differ from the prior run")
        expected_id, expected_sha256, _ = season_simulation_regeneration_identity(
            advancement_id=self.advancement_id,
            advancement_identity_sha256=self.advancement_identity_sha256,
            previous_simulation_id=self.previous_simulation_id,
            replacement_input_sha256=self.replacement_input_sha256,
            replacement_simulation_id=self.replacement_simulation_id,
            replacement_summary_id=self.replacement_summary_id,
            simulation_seed=self.simulation_seed,
            season_id=self.season_id,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("simulation regeneration identity does not match")
        return self
