"""Deterministic out-of-sample candidate comparison without promotion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.evaluation import (
    OutcomeCounts,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.features import PredictorSet
from pl_platform.domain.fixtures import FixtureStatus, MatchOutcome
from pl_platform.evaluation.catboost_model import CatBoostModelError
from pl_platform.evaluation.metrics import (
    MetricError,
    evaluate_probabilistic_predictions,
)
from pl_platform.prediction.domain import CompletedResultEvidence, UpcomingFeatureRow
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.training.retraining import (
    CandidateRetrainingManifest,
    CandidateRetrainingResult,
    RetrainingBaseline,
)

COMPARISON_REPORT_SCHEMA_VERSION: Final = 1
OPERATIONAL_COMPARISON_DATASET_ID: Final = "operational-comparison-v1"
OPERATIONAL_COMPARISON_PARTITION_ID: Final = "post-retraining-operational-holdout"
MINIMUM_COMPARISON_ROWS: Final = 30

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
ComparisonDecision = Literal[
    "insufficient_evidence",
    "retain_baseline",
    "candidate_review_recommended",
]


class ProbabilityClassifier(Protocol):
    """Minimum target-free classifier interface used by comparison."""

    predictor_names: tuple[str, ...]

    def predict_probabilities(self, predictors: PredictorSet) -> OutcomeProbabilities:
        """Return one three-way full-time-result probability vector."""


class CandidateComparisonFailureCode(StrEnum):
    """Stable fail-closed categories for candidate comparison."""

    CANDIDATE_INCOMPATIBLE = "candidate_incompatible"
    EMPTY_COMPARISON_INPUT = "empty_comparison_input"
    DUPLICATE_IDENTITY = "duplicate_identity"
    FEATURE_RESULT_MISMATCH = "feature_result_mismatch"
    SEALED_TARGET_PROHIBITED = "sealed_target_prohibited"
    CHRONOLOGY_VIOLATION = "chronology_violation"
    TRAINING_OVERLAP = "training_overlap"
    PREDICTOR_SCHEMA_INCOMPATIBLE = "predictor_schema_incompatible"
    PREDICTION_FAILED = "prediction_failed"


class CandidateComparisonError(ValueError):
    def __init__(
        self,
        code: CandidateComparisonFailureCode,
        safe_message: str,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(code.value)


class ComparisonFixtureLineage(BaseModel):
    """Exact feature/result identities for one comparison observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_example_id: UUID
    fixture_id: UUID
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    feature_id: UUID
    feature_identity_sha256: Sha256
    feature_cutoff_at: datetime
    result_id: UUID
    result_identity_sha256: Sha256
    result_observation_id: UUID
    result_cache_key_sha256: Sha256
    result_retrieved_at: datetime

    @field_validator("feature_cutoff_at", "result_retrieved_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("comparison lineage timestamps must be UTC")
        return value


class CandidateComparisonPayload(BaseModel):
    """Canonical report body whose checks determine the recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["pl-platform-candidate-comparison"] = (
        "pl-platform-candidate-comparison"
    )
    schema_version: Literal[1] = COMPARISON_REPORT_SCHEMA_VERSION
    status: Literal["comparison_complete"] = "comparison_complete"
    baseline_model_id: UUID
    baseline_artifact_id: UUID
    baseline_manifest_id: UUID
    baseline_artifact_manifest_sha256: Sha256
    candidate_id: UUID
    candidate_manifest_sha256: Sha256
    candidate_knowledge_cutoff_at: datetime
    comparison_knowledge_cutoff_at: datetime
    comparison_season_ids: tuple[str, ...] = Field(min_length=1)
    comparison_row_count: PositiveInt
    comparison_examples: tuple[ComparisonFixtureLineage, ...] = Field(min_length=1)
    minimum_comparison_rows: Literal[30] = MINIMUM_COMPARISON_ROWS
    baseline_metric: ProbabilisticMetricSummary
    candidate_metric: ProbabilisticMetricSummary
    log_loss_improvement: FiniteFloat
    multiclass_brier_improvement: FiniteFloat
    ranked_probability_score_improvement: FiniteFloat
    minimum_population_passed: bool
    outcome_coverage_passed: bool
    log_loss_improvement_passed: bool
    brier_noninferiority_passed: bool
    rps_noninferiority_passed: bool
    decision: ComparisonDecision
    registry_disposition: Literal["no_change"] = "no_change"
    human_review_required: Literal[True] = True

    @field_validator(
        "candidate_knowledge_cutoff_at",
        "comparison_knowledge_cutoff_at",
    )
    @classmethod
    def cutoffs_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("comparison cutoffs must be UTC")
        return value

    @model_validator(mode="after")
    def metrics_lineage_and_decision_must_agree(self) -> Self:
        if (
            self.comparison_row_count != len(self.comparison_examples)
            or self.baseline_metric.prediction_count != self.comparison_row_count
            or self.candidate_metric.prediction_count != self.comparison_row_count
            or self.baseline_metric.outcome_counts
            != self.candidate_metric.outcome_counts
            or self.baseline_metric.method != "catboost"
            or self.candidate_metric.method != "catboost"
        ):
            raise ValueError("comparison metrics do not cover one identical population")
        example_ids = tuple(
            item.comparison_example_id for item in self.comparison_examples
        )
        if example_ids != tuple(sorted(set(example_ids))):
            raise ValueError("comparison lineage must be unique and ordered")
        for values in (
            tuple(item.fixture_id for item in self.comparison_examples),
            tuple(item.feature_id for item in self.comparison_examples),
            tuple(item.result_id for item in self.comparison_examples),
            tuple(item.result_observation_id for item in self.comparison_examples),
        ):
            if len(values) != len(set(values)):
                raise ValueError("comparison lineage repeats an identity")
        if self.comparison_season_ids != tuple(
            sorted({item.season_id for item in self.comparison_examples})
        ):
            raise ValueError("comparison seasons do not match lineage")
        if self.comparison_knowledge_cutoff_at != max(
            item.result_retrieved_at for item in self.comparison_examples
        ):
            raise ValueError("comparison cutoff does not match result lineage")
        if any(
            item.feature_cutoff_at <= self.candidate_knowledge_cutoff_at
            for item in self.comparison_examples
        ):
            raise ValueError("comparison features do not follow candidate knowledge")

        log_improvement = (
            self.baseline_metric.mean_log_loss - self.candidate_metric.mean_log_loss
        )
        brier_improvement = (
            self.baseline_metric.mean_multiclass_brier_score
            - self.candidate_metric.mean_multiclass_brier_score
        )
        rps_improvement = (
            self.baseline_metric.mean_ranked_probability_score
            - self.candidate_metric.mean_ranked_probability_score
        )
        population_passed = self.comparison_row_count >= self.minimum_comparison_rows
        counts: OutcomeCounts = self.baseline_metric.outcome_counts
        coverage_passed = min(counts.home_win, counts.draw, counts.away_win) > 0
        log_passed = log_improvement > 0.0
        brier_passed = brier_improvement >= 0.0
        rps_passed = rps_improvement >= 0.0
        if not population_passed or not coverage_passed:
            decision: ComparisonDecision = "insufficient_evidence"
        elif log_passed and brier_passed and rps_passed:
            decision = "candidate_review_recommended"
        else:
            decision = "retain_baseline"
        expected = (
            log_improvement,
            brier_improvement,
            rps_improvement,
            population_passed,
            coverage_passed,
            log_passed,
            brier_passed,
            rps_passed,
            decision,
        )
        actual = (
            self.log_loss_improvement,
            self.multiclass_brier_improvement,
            self.ranked_probability_score_improvement,
            self.minimum_population_passed,
            self.outcome_coverage_passed,
            self.log_loss_improvement_passed,
            self.brier_noninferiority_passed,
            self.rps_noninferiority_passed,
            self.decision,
        )
        if actual != expected:
            raise ValueError("comparison decision does not match its metrics")
        return self


class CandidateComparisonReport(CandidateComparisonPayload):
    report_id: UUID

    @model_validator(mode="after")
    def report_identity_must_match_payload(self) -> Self:
        payload = CandidateComparisonPayload.model_validate(
            self.model_dump(exclude={"report_id"})
        )
        if self.report_id != deterministic_comparison_report_id(payload):
            raise ValueError("comparison report ID does not match its payload")
        return self


@dataclass(frozen=True, slots=True)
class CandidateComparisonResult:
    report: CandidateComparisonReport
    report_sha256: str


def deterministic_comparison_example_id(feature_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"pl-platform:{OPERATIONAL_COMPARISON_DATASET_ID}:{feature_id}",
    )


def deterministic_comparison_report_id(payload: CandidateComparisonPayload) -> UUID:
    digest = sha256_bytes(canonical_json_bytes(payload))
    return uuid5(
        NAMESPACE_URL,
        f"pl-platform:candidate-comparison:{COMPARISON_REPORT_SCHEMA_VERSION}|{digest}",
    )


def _prediction(
    *,
    feature: UpcomingFeatureRow,
    probabilities: OutcomeProbabilities,
    source_training_sha256: str,
    configuration_id: str,
) -> ProbabilisticPrediction:
    example_id = deterministic_comparison_example_id(feature.id)
    return ProbabilisticPrediction(
        id=deterministic_prediction_id(
            source_training_sha256=source_training_sha256,
            source_training_example_id=example_id,
            partition_id=OPERATIONAL_COMPARISON_PARTITION_ID,
            method="catboost",
            method_version=1,
            configuration_id=configuration_id,
        ),
        method="catboost",
        method_version=1,
        configuration_id=configuration_id,
        partition_id=OPERATIONAL_COMPARISON_PARTITION_ID,
        source_training_dataset_id=OPERATIONAL_COMPARISON_DATASET_ID,
        source_training_sha256=source_training_sha256,
        source_training_example_id=example_id,
        fixture_id=feature.fixture_id,
        season_id=feature.season_id,
        kickoff_at=feature.kickoff_at,
        feature_cutoff_at=feature.feature_cutoff_at,
        probabilities=probabilities,
    )


def _validate_candidate(
    baseline: RetrainingBaseline,
    candidate: CandidateRetrainingResult,
) -> CandidateRetrainingManifest:
    manifest = candidate.manifest
    if (
        sha256_bytes(canonical_json_bytes(manifest)) != candidate.manifest_sha256
        or manifest.baseline_model_id != baseline.model_id
        or manifest.baseline_artifact_id != baseline.artifact_id
        or manifest.baseline_manifest_id != baseline.manifest_id
        or manifest.baseline_artifact_manifest_sha256
        != baseline.artifact_manifest_sha256
        or manifest.source_training_manifest_sha256
        != baseline.source_training_manifest_sha256
        or manifest.predictor_schema != baseline.predictor_schema
        or manifest.configuration != baseline.configuration
    ):
        raise CandidateComparisonError(
            CandidateComparisonFailureCode.CANDIDATE_INCOMPATIBLE,
            "candidate manifest does not match the verified baseline",
        )
    return manifest


class CandidateComparisonWorkflow:
    """Compare one candidate and baseline on a later immutable holdout."""

    def run(
        self,
        *,
        baseline: RetrainingBaseline,
        baseline_classifier: ProbabilityClassifier,
        candidate: CandidateRetrainingResult,
        features: Sequence[UpcomingFeatureRow],
        results: Sequence[CompletedResultEvidence],
    ) -> CandidateComparisonResult:
        manifest = _validate_candidate(baseline, candidate)
        if not features or not results:
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.EMPTY_COMPARISON_INPUT,
                "candidate comparison requires completed holdout fixtures",
            )
        if (
            len({item.id for item in features}) != len(features)
            or len({item.fixture_id for item in features}) != len(features)
            or len({item.result_id for item in results}) != len(results)
            or len({item.observation_id for item in results}) != len(results)
            or len({item.fixture.id for item in results}) != len(results)
        ):
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.DUPLICATE_IDENTITY,
                "candidate comparison inputs repeat an identity",
            )
        results_by_fixture = {item.fixture.id: item for item in results}
        if {item.fixture_id for item in features} != set(results_by_fixture):
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.FEATURE_RESULT_MISMATCH,
                "comparison requires one result for every feature",
            )
        if any(
            item.season_id in baseline.excluded_season_ids for item in features
        ) or any(
            item.fixture.season_id in baseline.excluded_season_ids for item in results
        ):
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.SEALED_TARGET_PROHIBITED,
                "sealed target entered candidate comparison inputs",
            )
        trained_fixtures = {item.fixture_id for item in manifest.operational_examples}
        if trained_fixtures.intersection(item.fixture_id for item in features):
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.TRAINING_OVERLAP,
                "candidate training fixture entered the comparison population",
            )
        expected_names = baseline.predictor_schema.predictor_names
        if (
            baseline_classifier.predictor_names != expected_names
            or candidate.classifier.predictor_names != expected_names
            or any(
                feature.predictors.schema_id != baseline.predictor_schema.id
                or feature.predictors.schema_version
                != baseline.predictor_schema.version
                or tuple(item.name for item in feature.predictors.values)
                != expected_names
                for feature in features
            )
        ):
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE,
                "comparison classifiers or features use an incompatible schema",
            )

        ordered_features = tuple(
            sorted(features, key=lambda item: (item.feature_cutoff_at, item.id))
        )
        lineage: list[ComparisonFixtureLineage] = []
        baseline_predictions: list[ProbabilisticPrediction] = []
        candidate_predictions: list[ProbabilisticPrediction] = []
        actual_outcomes: dict[UUID, MatchOutcome] = {}
        for feature in ordered_features:
            result = results_by_fixture[feature.fixture_id]
            completed = result.fixture
            if (
                feature.fixture_id != completed.id
                or feature.competition_id != completed.competition_id
                or feature.season_id != completed.season_id
                or feature.home_team_id != completed.home_team_id
                or feature.away_team_id != completed.away_team_id
                or feature.kickoff_at != completed.kickoff_at
                or feature.fixture_evidence.fixture.status
                is not FixtureStatus.SCHEDULED
                or completed.status is not FixtureStatus.FINISHED
                or completed.outcome is None
                or completed.full_time_score is None
            ):
                raise CandidateComparisonError(
                    CandidateComparisonFailureCode.FEATURE_RESULT_MISMATCH,
                    "comparison feature and result do not describe one fixture",
                )
            if (
                feature.feature_cutoff_at <= manifest.knowledge_cutoff_at
                or result.retrieved_at < feature.kickoff_at
                or result.retrieved_at <= manifest.knowledge_cutoff_at
            ):
                raise CandidateComparisonError(
                    CandidateComparisonFailureCode.CHRONOLOGY_VIOLATION,
                    "comparison evidence does not follow candidate knowledge",
                )
            example_id = deterministic_comparison_example_id(feature.id)
            try:
                baseline_probability = baseline_classifier.predict_probabilities(
                    feature.predictors
                )
                candidate_probability = candidate.classifier.predict_probabilities(
                    feature.predictors
                )
            except (CatBoostModelError, ValueError) as exc:
                raise CandidateComparisonError(
                    CandidateComparisonFailureCode.PREDICTION_FAILED,
                    "candidate comparison probability generation failed",
                ) from exc
            baseline_predictions.append(
                _prediction(
                    feature=feature,
                    probabilities=baseline_probability,
                    source_training_sha256=baseline.source_training_manifest_sha256,
                    configuration_id=f"baseline:{baseline.configuration.id}",
                )
            )
            candidate_predictions.append(
                _prediction(
                    feature=feature,
                    probabilities=candidate_probability,
                    source_training_sha256=manifest.combined_training_sha256,
                    configuration_id=f"candidate:{manifest.candidate_id}",
                )
            )
            actual_outcomes[example_id] = completed.outcome
            lineage.append(
                ComparisonFixtureLineage(
                    comparison_example_id=example_id,
                    fixture_id=feature.fixture_id,
                    season_id=feature.season_id,
                    feature_id=feature.id,
                    feature_identity_sha256=feature.identity_sha256,
                    feature_cutoff_at=feature.feature_cutoff_at,
                    result_id=result.result_id,
                    result_identity_sha256=result.result_identity_sha256,
                    result_observation_id=result.observation_id,
                    result_cache_key_sha256=result.cache_key_sha256,
                    result_retrieved_at=result.retrieved_at,
                )
            )
        try:
            baseline_metric = evaluate_probabilistic_predictions(
                baseline_predictions, actual_outcomes
            )
            candidate_metric = evaluate_probabilistic_predictions(
                candidate_predictions, actual_outcomes
            )
        except MetricError as exc:
            raise CandidateComparisonError(
                CandidateComparisonFailureCode.PREDICTION_FAILED,
                "candidate comparison metric calculation failed",
            ) from exc

        ordered_lineage = tuple(
            sorted(lineage, key=lambda item: item.comparison_example_id)
        )
        counts = baseline_metric.outcome_counts
        log_improvement = baseline_metric.mean_log_loss - candidate_metric.mean_log_loss
        brier_improvement = (
            baseline_metric.mean_multiclass_brier_score
            - candidate_metric.mean_multiclass_brier_score
        )
        rps_improvement = (
            baseline_metric.mean_ranked_probability_score
            - candidate_metric.mean_ranked_probability_score
        )
        population_passed = len(ordered_lineage) >= MINIMUM_COMPARISON_ROWS
        outcome_coverage_passed = min(counts.home_win, counts.draw, counts.away_win) > 0
        log_passed = log_improvement > 0.0
        brier_passed = brier_improvement >= 0.0
        rps_passed = rps_improvement >= 0.0
        if not population_passed or not outcome_coverage_passed:
            decision: ComparisonDecision = "insufficient_evidence"
        elif log_passed and brier_passed and rps_passed:
            decision = "candidate_review_recommended"
        else:
            decision = "retain_baseline"
        payload = CandidateComparisonPayload(
            baseline_model_id=baseline.model_id,
            baseline_artifact_id=baseline.artifact_id,
            baseline_manifest_id=baseline.manifest_id,
            baseline_artifact_manifest_sha256=(baseline.artifact_manifest_sha256),
            candidate_id=manifest.candidate_id,
            candidate_manifest_sha256=candidate.manifest_sha256,
            candidate_knowledge_cutoff_at=manifest.knowledge_cutoff_at,
            comparison_knowledge_cutoff_at=max(
                item.result_retrieved_at for item in ordered_lineage
            ),
            comparison_season_ids=tuple(
                sorted({item.season_id for item in ordered_lineage})
            ),
            comparison_row_count=len(ordered_lineage),
            comparison_examples=ordered_lineage,
            baseline_metric=baseline_metric,
            candidate_metric=candidate_metric,
            log_loss_improvement=log_improvement,
            multiclass_brier_improvement=brier_improvement,
            ranked_probability_score_improvement=rps_improvement,
            minimum_population_passed=population_passed,
            outcome_coverage_passed=outcome_coverage_passed,
            log_loss_improvement_passed=log_passed,
            brier_noninferiority_passed=brier_passed,
            rps_noninferiority_passed=rps_passed,
            decision=decision,
        )
        report = CandidateComparisonReport(
            **payload.model_dump(),
            report_id=deterministic_comparison_report_id(payload),
        )
        return CandidateComparisonResult(
            report=report,
            report_sha256=sha256_bytes(canonical_json_bytes(report)),
        )
