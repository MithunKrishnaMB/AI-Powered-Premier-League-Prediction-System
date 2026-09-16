"""Deterministic, explicit candidate retraining without promotion or scheduling."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.features import TrainingLabel
from pl_platform.domain.fixtures import FixtureStatus
from pl_platform.domain.training import (
    TrainingExample,
    deterministic_training_example_id,
)
from pl_platform.evaluation.catboost_model import (
    CatBoostModelError,
    CatBoostParameters,
    FittedCatBoostClassifier,
    fit_catboost_classifier,
)
from pl_platform.evaluation.walk_forward import DEVELOPMENT_SEASONS, EXCLUDED_SEASONS
from pl_platform.features.materialize import FeaturePredictorSchema
from pl_platform.prediction.domain import CompletedResultEvidence, UpcomingFeatureRow
from pl_platform.registry.artifact_manifest import (
    ModelArtifactManifest,
    canonical_json_bytes,
    sha256_bytes,
)

RETRAINING_CANDIDATE_SCHEMA_VERSION: Final = 1
OPERATIONAL_RETRAINING_DATASET_ID: Final = "operational-retraining-v1"
RETRAINING_PARAMETERS: Final = CatBoostParameters(
    id="catboost-depth6-regularized",
    iterations=200,
    depth=6,
    learning_rate=0.05,
    l2_leaf_reg=10.0,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class CandidateRetrainingFailureCode(StrEnum):
    """Stable fail-closed categories for explicit candidate retraining."""

    BASELINE_INCOMPATIBLE = "baseline_incompatible"
    EMPTY_OPERATIONAL_INPUT = "empty_operational_input"
    SEALED_TARGET_PROHIBITED = "sealed_target_prohibited"
    CHRONOLOGY_VIOLATION = "chronology_violation"
    FEATURE_RESULT_MISMATCH = "feature_result_mismatch"
    PREDICTOR_SCHEMA_INCOMPATIBLE = "predictor_schema_incompatible"
    DUPLICATE_IDENTITY = "duplicate_identity"
    FIT_FAILED = "fit_failed"


class CandidateRetrainingError(ValueError):
    def __init__(
        self,
        code: CandidateRetrainingFailureCode,
        safe_message: str,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(code.value)


class RetrainingBaseline(BaseModel):
    """Verified artifact facts required without carrying registry state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: UUID
    artifact_id: UUID
    manifest_id: UUID
    artifact_manifest_sha256: Sha256
    source_training_manifest_sha256: Sha256
    predictor_schema: FeaturePredictorSchema
    configuration: CatBoostParameters
    development_season_ids: tuple[str, ...]
    excluded_season_ids: tuple[str, ...]

    @model_validator(mode="after")
    def policy_must_match_the_accepted_development_boundary(self) -> Self:
        if (
            self.configuration != RETRAINING_PARAMETERS
            or self.development_season_ids != DEVELOPMENT_SEASONS
            or self.excluded_season_ids != EXCLUDED_SEASONS
        ):
            raise ValueError("retraining baseline policy is incompatible")
        return self

    @classmethod
    def from_artifact(
        cls,
        manifest: ModelArtifactManifest,
        *,
        manifest_sha256: str,
    ) -> RetrainingBaseline:
        if sha256_bytes(canonical_json_bytes(manifest)) != manifest_sha256:
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
                "baseline artifact manifest checksum is incompatible",
            )
        try:
            return cls(
                model_id=manifest.model_id,
                artifact_id=manifest.artifact_id,
                manifest_id=manifest.manifest_id,
                artifact_manifest_sha256=manifest_sha256,
                source_training_manifest_sha256=(
                    manifest.provenance.training_manifest_sha256
                ),
                predictor_schema=manifest.predictors.predictor_schema,
                configuration=manifest.model.classifier.configuration,
                development_season_ids=manifest.provenance.development_season_ids,
                excluded_season_ids=manifest.provenance.untouched_test_season_ids,
            )
        except ValueError as exc:
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
                "baseline artifact policy is incompatible",
            ) from exc


class OperationalTrainingLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    training_example_id: UUID
    fixture_id: UUID
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    feature_id: UUID
    feature_identity_sha256: Sha256
    result_id: UUID
    result_identity_sha256: Sha256
    result_observation_id: UUID
    result_cache_key_sha256: Sha256
    result_retrieved_at: datetime

    @field_validator("result_retrieved_at")
    @classmethod
    def retrieval_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("result retrieval must be timezone-aware UTC")
        return value


class CandidateRetrainingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["pl-platform-candidate-retraining"] = (
        "pl-platform-candidate-retraining"
    )
    schema_version: Literal[1] = RETRAINING_CANDIDATE_SCHEMA_VERSION
    status: Literal["candidate_unassessed"] = "candidate_unassessed"
    baseline_model_id: UUID
    baseline_artifact_id: UUID
    baseline_manifest_id: UUID
    baseline_artifact_manifest_sha256: Sha256
    source_training_manifest_sha256: Sha256
    baseline_training_sha256: Sha256
    operational_training_sha256: Sha256
    combined_training_sha256: Sha256
    baseline_row_count: PositiveInt
    operational_row_count: PositiveInt
    combined_row_count: PositiveInt
    baseline_season_ids: tuple[str, ...]
    operational_season_ids: tuple[str, ...]
    excluded_season_ids: tuple[str, ...]
    predictor_schema: FeaturePredictorSchema
    configuration: CatBoostParameters
    knowledge_cutoff_at: datetime
    operational_examples: tuple[OperationalTrainingLineage, ...] = Field(min_length=1)

    @field_validator("knowledge_cutoff_at")
    @classmethod
    def cutoff_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("retraining knowledge cutoff must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def counts_seasons_and_lineage_must_be_canonical(self) -> Self:
        if self.combined_row_count != (
            self.baseline_row_count + self.operational_row_count
        ):
            raise ValueError("combined retraining count does not add up")
        if self.operational_row_count != len(self.operational_examples):
            raise ValueError("operational retraining count does not match lineage")
        if (
            self.baseline_season_ids != DEVELOPMENT_SEASONS
            or self.excluded_season_ids != EXCLUDED_SEASONS
            or self.configuration != RETRAINING_PARAMETERS
        ):
            raise ValueError("candidate retraining policy is incompatible")
        if self.operational_season_ids != tuple(
            sorted(set(self.operational_season_ids))
        ):
            raise ValueError(
                "operational retraining seasons must be unique and ordered"
            )
        if set(self.operational_season_ids).intersection(self.excluded_season_ids):
            raise ValueError("excluded season entered operational retraining")
        lineage_ids = tuple(
            item.training_example_id for item in self.operational_examples
        )
        if lineage_ids != tuple(sorted(set(lineage_ids))):
            raise ValueError(
                "operational retraining lineage must be unique and ordered"
            )
        for values in (
            tuple(item.fixture_id for item in self.operational_examples),
            tuple(item.feature_id for item in self.operational_examples),
            tuple(item.result_id for item in self.operational_examples),
            tuple(item.result_observation_id for item in self.operational_examples),
        ):
            if len(values) != len(set(values)):
                raise ValueError("operational retraining lineage repeats an identity")
        if self.operational_season_ids != tuple(
            sorted({item.season_id for item in self.operational_examples})
        ):
            raise ValueError("operational seasons do not match result lineage")
        if self.knowledge_cutoff_at != max(
            item.result_retrieved_at for item in self.operational_examples
        ):
            raise ValueError("knowledge cutoff does not match result lineage")
        return self


class CandidateRetrainingManifest(CandidateRetrainingPayload):
    candidate_id: UUID

    @model_validator(mode="after")
    def candidate_identity_must_match_payload(self) -> Self:
        payload = CandidateRetrainingPayload.model_validate(
            self.model_dump(exclude={"candidate_id"})
        )
        if self.candidate_id != deterministic_candidate_id(payload):
            raise ValueError("candidate ID does not match retraining payload")
        return self


@dataclass(frozen=True, slots=True)
class CandidateRetrainingResult:
    manifest: CandidateRetrainingManifest
    manifest_sha256: str
    classifier: FittedCatBoostClassifier


type CandidateFitter = Callable[
    [Sequence[TrainingExample], tuple[str, ...], CatBoostParameters],
    FittedCatBoostClassifier,
]


def deterministic_candidate_id(payload: CandidateRetrainingPayload) -> UUID:
    digest = sha256_bytes(canonical_json_bytes(payload))
    return uuid5(
        NAMESPACE_URL,
        f"pl-platform:candidate-retraining:{RETRAINING_CANDIDATE_SCHEMA_VERSION}|{digest}",
    )


def _training_bytes(examples: Sequence[TrainingExample]) -> bytes:
    ordered = tuple(
        sorted(
            examples,
            key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
        )
    )
    return b"".join(canonical_json_bytes(item) for item in ordered)


def _validate_predictors(
    examples: Sequence[TrainingExample],
    schema: FeaturePredictorSchema,
) -> None:
    expected_names = schema.predictor_names
    if any(
        example.predictors.schema_id != schema.id
        or example.predictors.schema_version != schema.version
        or tuple(item.name for item in example.predictors.values) != expected_names
        for example in examples
    ):
        raise CandidateRetrainingError(
            CandidateRetrainingFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE,
            "retraining examples do not match the baseline predictor schema",
        )


def _operational_example(
    feature: UpcomingFeatureRow,
    result: CompletedResultEvidence,
) -> tuple[TrainingExample, OperationalTrainingLineage]:
    completed = result.fixture
    if (
        feature.fixture_id != completed.id
        or feature.competition_id != completed.competition_id
        or feature.season_id != completed.season_id
        or feature.home_team_id != completed.home_team_id
        or feature.away_team_id != completed.away_team_id
        or feature.kickoff_at != completed.kickoff_at
        or feature.fixture_evidence.fixture.status is not FixtureStatus.SCHEDULED
        or completed.status is not FixtureStatus.FINISHED
        or completed.full_time_score is None
        or completed.outcome is None
    ):
        raise CandidateRetrainingError(
            CandidateRetrainingFailureCode.FEATURE_RESULT_MISMATCH,
            "pre-match feature and official result do not describe one fixture",
        )
    if result.retrieved_at < feature.kickoff_at:
        raise CandidateRetrainingError(
            CandidateRetrainingFailureCode.CHRONOLOGY_VIOLATION,
            "official result was retrieved before fixture kickoff",
        )
    example_id = deterministic_training_example_id(
        feature.id,
        OPERATIONAL_RETRAINING_DATASET_ID,
    )
    example = TrainingExample(
        id=example_id,
        feature_row_id=feature.id,
        fixture_id=feature.fixture_id,
        competition_id="eng-premier-league",
        season_id=feature.season_id,
        home_team_id=feature.home_team_id,
        away_team_id=feature.away_team_id,
        kickoff_at=feature.kickoff_at,
        kickoff_precision=feature.fixture_evidence.fixture.kickoff_precision,
        feature_cutoff_at=feature.feature_cutoff_at,
        predictors=feature.predictors,
        target=TrainingLabel(
            outcome=completed.outcome,
            home_goals=completed.full_time_score.home,
            away_goals=completed.full_time_score.away,
        ),
        source_feature_dataset_id=OPERATIONAL_RETRAINING_DATASET_ID,
    )
    lineage = OperationalTrainingLineage(
        training_example_id=example.id,
        fixture_id=feature.fixture_id,
        season_id=feature.season_id,
        feature_id=feature.id,
        feature_identity_sha256=feature.identity_sha256,
        result_id=result.result_id,
        result_identity_sha256=result.result_identity_sha256,
        result_observation_id=result.observation_id,
        result_cache_key_sha256=result.cache_key_sha256,
        result_retrieved_at=result.retrieved_at,
    )
    return example, lineage


class CandidateRetrainingWorkflow:
    """Refit one unassessed candidate from explicit verified in-memory inputs."""

    def __init__(self, *, fitter: CandidateFitter = fit_catboost_classifier) -> None:
        self._fitter = fitter

    def run(
        self,
        *,
        baseline: RetrainingBaseline,
        baseline_examples: Sequence[TrainingExample],
        features: Sequence[UpcomingFeatureRow],
        results: Sequence[CompletedResultEvidence],
    ) -> CandidateRetrainingResult:
        if not features or not results:
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.EMPTY_OPERATIONAL_INPUT,
                "candidate retraining requires completed operational fixtures",
            )
        feature_identity_sets = (
            {item.fixture_id for item in features},
            {item.id for item in features},
        )
        result_identity_sets = (
            {item.fixture.id for item in results},
            {item.result_id for item in results},
            {item.observation_id for item in results},
        )
        if any(len(values) != len(features) for values in feature_identity_sets) or any(
            len(values) != len(results) for values in result_identity_sets
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.DUPLICATE_IDENTITY,
                "candidate retraining inputs repeat a fixture identity",
            )
        results_by_fixture = {item.fixture.id: item for item in results}
        if {item.fixture_id for item in features} != set(results_by_fixture):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.FEATURE_RESULT_MISMATCH,
                "candidate retraining requires one result for every feature",
            )
        if any(
            item.season_id in baseline.excluded_season_ids for item in features
        ) or any(
            item.fixture.season_id in baseline.excluded_season_ids for item in results
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.SEALED_TARGET_PROHIBITED,
                "sealed target entered operational retraining inputs",
            )

        ordered_baseline = tuple(
            sorted(
                baseline_examples,
                key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
            )
        )
        baseline_identity_sets = (
            {item.id for item in ordered_baseline},
            {item.feature_row_id for item in ordered_baseline},
            {item.fixture_id for item in ordered_baseline},
        )
        if not ordered_baseline or any(
            len(values) != len(ordered_baseline) for values in baseline_identity_sets
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
                "baseline training examples are missing or duplicate",
            )
        baseline_seasons = tuple(sorted({item.season_id for item in ordered_baseline}))
        if any(
            item.season_id in baseline.excluded_season_ids for item in ordered_baseline
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.SEALED_TARGET_PROHIBITED,
                "sealed target entered baseline retraining examples",
            )
        if baseline_seasons != baseline.development_season_ids:
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
                "baseline examples do not cover the accepted development seasons",
            )
        _validate_predictors(ordered_baseline, baseline.predictor_schema)

        operational_pairs = tuple(
            _operational_example(feature, results_by_fixture[feature.fixture_id])
            for feature in sorted(
                features,
                key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
            )
        )
        operational = tuple(item[0] for item in operational_pairs)
        last_development_year = max(
            int(season_id[:4]) for season_id in baseline.development_season_ids
        )
        if any(
            int(item.season_id[:4]) <= last_development_year for item in operational
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.CHRONOLOGY_VIOLATION,
                "operational retraining season does not follow development data",
            )
        if {item.fixture_id for item in ordered_baseline}.intersection(
            item.fixture_id for item in operational
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.DUPLICATE_IDENTITY,
                "operational fixture already exists in baseline training data",
            )
        _validate_predictors(operational, baseline.predictor_schema)

        combined = tuple(
            sorted(
                (*ordered_baseline, *operational),
                key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
            )
        )
        try:
            classifier = self._fitter(
                combined,
                baseline.predictor_schema.predictor_names,
                RETRAINING_PARAMETERS,
            )
        except (CatBoostModelError, ValueError) as exc:
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.FIT_FAILED,
                "candidate classifier fitting failed",
            ) from exc
        if (
            classifier.predictor_names != baseline.predictor_schema.predictor_names
            or classifier.diagnostics.candidate_id != RETRAINING_PARAMETERS.id
            or classifier.diagnostics.training_row_count != len(combined)
            or classifier.diagnostics.predictor_count
            != baseline.predictor_schema.predictor_count
            or classifier.diagnostics.tree_count != RETRAINING_PARAMETERS.iterations
        ):
            raise CandidateRetrainingError(
                CandidateRetrainingFailureCode.FIT_FAILED,
                "candidate classifier diagnostics are incompatible",
            )

        lineage = tuple(
            sorted(
                (item[1] for item in operational_pairs),
                key=lambda item: item.training_example_id,
            )
        )
        baseline_bytes = _training_bytes(ordered_baseline)
        operational_bytes = _training_bytes(operational)
        combined_bytes = _training_bytes(combined)
        payload = CandidateRetrainingPayload(
            baseline_model_id=baseline.model_id,
            baseline_artifact_id=baseline.artifact_id,
            baseline_manifest_id=baseline.manifest_id,
            baseline_artifact_manifest_sha256=(baseline.artifact_manifest_sha256),
            source_training_manifest_sha256=(baseline.source_training_manifest_sha256),
            baseline_training_sha256=sha256_bytes(baseline_bytes),
            operational_training_sha256=sha256_bytes(operational_bytes),
            combined_training_sha256=sha256_bytes(combined_bytes),
            baseline_row_count=len(ordered_baseline),
            operational_row_count=len(operational),
            combined_row_count=len(combined),
            baseline_season_ids=baseline.development_season_ids,
            operational_season_ids=tuple(
                sorted({item.season_id for item in operational})
            ),
            excluded_season_ids=baseline.excluded_season_ids,
            predictor_schema=baseline.predictor_schema,
            configuration=RETRAINING_PARAMETERS,
            knowledge_cutoff_at=max(item.result_retrieved_at for item in lineage),
            operational_examples=lineage,
        )
        manifest = CandidateRetrainingManifest(
            **payload.model_dump(),
            candidate_id=deterministic_candidate_id(payload),
        )
        return CandidateRetrainingResult(
            manifest=manifest,
            manifest_sha256=sha256_bytes(canonical_json_bytes(manifest)),
            classifier=classifier,
        )
