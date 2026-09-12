"""Materialize calibrated CatBoost, Poisson and Dixon-Coles development results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import (
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
)
from pl_platform.evaluation.calibration import (
    CALIBRATION_CONFIGURATION_ID,
    CALIBRATION_EVALUATION_SEASONS,
    CALIBRATION_METHOD_VERSION,
    CalibrationEvaluationResult,
    CalibrationFoldResult,
    TemperatureCalibrationParameters,
    TemperatureFitDiagnostics,
    evaluate_expanding_temperature_calibration,
)
from pl_platform.evaluation.catboost_materialize import (
    CatBoostTuningDatasetManifest,
    load_catboost_tuning_dataset,
)
from pl_platform.evaluation.score_models import (
    DIXON_COLES_CONFIGURATION_ID,
    MAX_SCORE_GOALS,
    POISSON_CONFIGURATION_ID,
    SCORE_MODEL_METHOD_VERSION,
    DixonColesFitDiagnostics,
    PoissonFitDiagnostics,
    ScoreModelEvaluationResult,
    ScoreModelFoldResult,
    evaluate_score_models_walk_forward,
)
from pl_platform.evaluation.test_freeze import load_test_freeze
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    EXCLUDED_SEASONS,
    walk_forward_windows,
)
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    load_training_dataset,
    materialize_training_dataset,
)

ADVANCED_EVALUATION_SCHEMA_VERSION: Final = 1
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class AdvancedEvaluationError(ValueError):
    """Advanced evaluation artifacts violate identity or temporal provenance."""


class CatBoostTuningSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    manifest_sha256: Sha256
    selected_candidate_id: str = Field(min_length=1)
    selected_prediction_row_count: PositiveInt
    selected_predictions_sha256: Sha256
    test_freeze_manifest_sha256: Sha256


class TemperatureFitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: Annotated[float, Field(strict=True, gt=0.0, allow_inf_nan=False)]
    training_prediction_count: PositiveInt
    training_log_loss_before: NonNegativeFloat
    training_log_loss_after: NonNegativeFloat


class CalibrationFoldReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    partition_id: str = Field(min_length=1)
    calibration_season_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    fit: TemperatureFitReport
    uncalibrated_metric: ProbabilisticMetricSummary
    calibrated_metric: ProbabilisticMetricSummary

    @model_validator(mode="after")
    def methods_and_counts_must_match(self) -> Self:
        if self.uncalibrated_metric.method != "catboost":
            msg = "calibration baseline metric must be CatBoost"
            raise ValueError(msg)
        if self.calibrated_metric.method != "catboost_calibrated":
            msg = "calibrated metric must use the calibrated CatBoost method"
            raise ValueError(msg)
        if (
            self.uncalibrated_metric.prediction_count
            != self.calibrated_metric.prediction_count
        ):
            msg = "paired calibration metric counts must match"
            raise ValueError(msg)
        return self


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_version: Literal[1]
    configuration_id: Literal["temperature-scaling-v1"]
    protocol: Literal["expanding_prior_oof_temperature_scaling"]
    parameters: TemperatureCalibrationParameters
    folds: tuple[CalibrationFoldReport, ...] = Field(min_length=4, max_length=4)
    aggregate_uncalibrated_metric: ProbabilisticMetricSummary
    aggregate_calibrated_metric: ProbabilisticMetricSummary
    selection_rule: Literal["log_loss_then_brier_then_rps"]
    selected_strategy: Literal["identity", "temperature_scaling"]
    final_fit: TemperatureFitReport

    @model_validator(mode="after")
    def aggregates_and_selection_must_match(self) -> Self:
        if (
            self.aggregate_uncalibrated_metric.method != "catboost"
            or self.aggregate_calibrated_metric.method != "catboost_calibrated"
        ):
            msg = "calibration aggregate metrics have unsupported methods"
            raise ValueError(msg)
        expected_count = sum(
            fold.calibrated_metric.prediction_count for fold in self.folds
        )
        if (
            self.aggregate_uncalibrated_metric.prediction_count != expected_count
            or self.aggregate_calibrated_metric.prediction_count != expected_count
        ):
            msg = "calibration aggregates do not cover every fold"
            raise ValueError(msg)

        def metric_key(
            metric: ProbabilisticMetricSummary,
        ) -> tuple[float, float, float]:
            return (
                metric.mean_log_loss,
                metric.mean_multiclass_brier_score,
                metric.mean_ranked_probability_score,
            )

        expected_strategy = (
            "temperature_scaling"
            if metric_key(self.aggregate_calibrated_metric)
            < metric_key(self.aggregate_uncalibrated_metric)
            else "identity"
        )
        if self.selected_strategy != expected_strategy:
            msg = "calibration strategy does not satisfy the selection rule"
            raise ValueError(msg)
        if not (
            self.parameters.minimum_temperature
            <= self.final_fit.temperature
            <= self.parameters.maximum_temperature
        ):
            msg = "final calibration temperature is outside its contract"
            raise ValueError(msg)
        return self


class PoissonFitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    training_row_count: PositiveInt
    team_count: PositiveInt
    optimizer_iterations: PositiveInt
    final_objective: FiniteFloat
    mean_home_goals: Annotated[float, Field(strict=True, gt=0.0, allow_inf_nan=False)]
    mean_away_goals: Annotated[float, Field(strict=True, gt=0.0, allow_inf_nan=False)]


class DixonColesFitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    training_row_count: PositiveInt
    rho: FiniteFloat
    low_score_row_count: Annotated[int, Field(strict=True, ge=0)]
    adjustment_negative_log_likelihood: FiniteFloat


class PoissonOptimizerContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    optimizer_iterations: PositiveInt
    learning_rate: Annotated[
        float, Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False)
    ]
    beta_one: Annotated[float, Field(strict=True, gt=0.0, lt=1.0, allow_inf_nan=False)]
    beta_two: Annotated[float, Field(strict=True, gt=0.0, lt=1.0, allow_inf_nan=False)]
    epsilon: Annotated[float, Field(strict=True, gt=0.0, allow_inf_nan=False)]
    l2_strength: NonNegativeFloat
    minimum_expected_goals: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ]
    maximum_expected_goals: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ]

    @model_validator(mode="after")
    def goal_bounds_must_be_ordered(self) -> Self:
        if self.minimum_expected_goals >= self.maximum_expected_goals:
            msg = "Poisson optimizer expected-goal bounds are invalid"
            raise ValueError(msg)
        return self


class DixonColesContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fit: Literal["training_window_only_scalar_likelihood"]
    optimizer_iterations: PositiveInt
    rho_minimum: Annotated[
        float, Field(strict=True, ge=-0.15, le=0.025, allow_inf_nan=False)
    ]
    rho_maximum: Annotated[
        float, Field(strict=True, ge=-0.15, le=0.025, allow_inf_nan=False)
    ]
    adjusted_scores: Literal["0-0,0-1,1-0,1-1"]

    @model_validator(mode="after")
    def rho_bounds_must_be_ordered(self) -> Self:
        if self.rho_minimum >= self.rho_maximum:
            msg = "Dixon-Coles contract rho bounds are invalid"
            raise ValueError(msg)
        return self


class ScoreModelFoldReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    partition_id: str = Field(min_length=1)
    reference_season_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    poisson_fit: PoissonFitReport
    dixon_coles_fit: DixonColesFitReport
    poisson_metric: ProbabilisticMetricSummary
    dixon_coles_metric: ProbabilisticMetricSummary

    @model_validator(mode="after")
    def methods_and_counts_must_match(self) -> Self:
        if self.poisson_metric.method != "poisson":
            msg = "Poisson fold metric has the wrong method"
            raise ValueError(msg)
        if self.dixon_coles_metric.method != "dixon_coles":
            msg = "Dixon-Coles fold metric has the wrong method"
            raise ValueError(msg)
        if (
            self.poisson_metric.prediction_count
            != self.dixon_coles_metric.prediction_count
        ):
            msg = "score-model fold metric counts must match"
            raise ValueError(msg)
        return self


class ScoreModelReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_version: Literal[1]
    poisson_configuration_id: Literal["independent-poisson-v1"]
    dixon_coles_configuration_id: Literal["dixon-coles-v1"]
    predictor_contract: Literal["canonical_team_ids_and_training_window_scores_only"]
    score_grid_maximum_goals_per_team: Literal[40]
    poisson_optimizer: PoissonOptimizerContract
    dixon_coles_contract: DixonColesContract
    folds: tuple[ScoreModelFoldReport, ...] = Field(min_length=5, max_length=5)
    aggregate_poisson_metric: ProbabilisticMetricSummary
    aggregate_dixon_coles_metric: ProbabilisticMetricSummary
    final_poisson_fit: PoissonFitReport
    final_dixon_coles_fit: DixonColesFitReport

    @model_validator(mode="after")
    def aggregates_and_fit_contracts_must_match(self) -> Self:
        if (
            self.aggregate_poisson_metric.method != "poisson"
            or self.aggregate_dixon_coles_metric.method != "dixon_coles"
        ):
            msg = "score-model aggregate metrics have unsupported methods"
            raise ValueError(msg)
        if self.aggregate_poisson_metric.prediction_count != sum(
            fold.poisson_metric.prediction_count for fold in self.folds
        ) or self.aggregate_dixon_coles_metric.prediction_count != sum(
            fold.dixon_coles_metric.prediction_count for fold in self.folds
        ):
            msg = "score-model aggregates do not cover every fold"
            raise ValueError(msg)
        fits = (
            *(fold.poisson_fit for fold in self.folds),
            self.final_poisson_fit,
        )
        if any(
            fit.optimizer_iterations != self.poisson_optimizer.optimizer_iterations
            for fit in fits
        ):
            msg = "Poisson fit iterations do not match the optimizer contract"
            raise ValueError(msg)
        dixon_coles_fits = (
            *(fold.dixon_coles_fit for fold in self.folds),
            self.final_dixon_coles_fit,
        )
        if any(
            not self.dixon_coles_contract.rho_minimum
            <= fit.rho
            <= self.dixon_coles_contract.rho_maximum
            for fit in dixon_coles_fits
        ):
            msg = "Dixon-Coles fit rho is outside its contract"
            raise ValueError(msg)
        return self


class AdvancedEvaluationManifest(BaseModel):
    """Strict standalone lineage for Steps 3.6 through 3.8."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: Literal["advanced-evaluation-v1-2015-2016-to-2024-2025"]
    competition_id: Literal["eng-premier-league"]
    development_season_ids: tuple[str, ...]
    untouched_test_season_ids: tuple[str, ...]
    source_training_manifest_sha256: Sha256
    source_training_manifest: TrainingDatasetManifest
    source_catboost_tuning: CatBoostTuningSource
    prediction_row_count: PositiveInt
    predictions_sha256: Sha256
    prediction_methods: tuple[
        Literal["catboost_calibrated"],
        Literal["poisson"],
        Literal["dixon_coles"],
    ]
    predictions_ordered_by: tuple[
        Literal["method"],
        Literal["partition_id"],
        Literal["feature_cutoff_at"],
        Literal["kickoff_at"],
        Literal["training_example_id"],
    ]
    calibration: CalibrationReport
    score_models: ScoreModelReport

    @model_validator(mode="after")
    def boundary_counts_and_lineage_must_match(self) -> Self:
        if self.development_season_ids != DEVELOPMENT_SEASONS:
            msg = "advanced evaluation has an unsupported development window"
            raise ValueError(msg)
        if self.untouched_test_season_ids != EXCLUDED_SEASONS:
            msg = "advanced evaluation has an unsupported untouched test window"
            raise ValueError(msg)
        training_payload = _stable_model_bytes(self.source_training_manifest)
        if _sha256(training_payload) != self.source_training_manifest_sha256:
            msg = "embedded training manifest does not match its checksum"
            raise ValueError(msg)
        source_counts = {
            source.season_id: source.feature_row_count
            for source in self.source_training_manifest.source_feature_datasets
        }
        expected_calibration_rows = sum(
            source_counts[season_id] for season_id in CALIBRATION_EVALUATION_SEASONS
        )
        expected_score_rows = sum(
            source_counts[window.evaluation_season_ids[0]]
            for window in walk_forward_windows()
        )
        expected_total = expected_calibration_rows + 2 * expected_score_rows
        if self.prediction_row_count != expected_total:
            msg = "advanced prediction count does not match verified season inputs"
            raise ValueError(msg)
        if (
            self.source_catboost_tuning.selected_prediction_row_count
            != expected_score_rows
        ):
            msg = "CatBoost source count does not cover every development fold"
            raise ValueError(msg)
        if (
            self.calibration.aggregate_calibrated_metric.prediction_count
            != expected_calibration_rows
            or self.score_models.aggregate_poisson_metric.prediction_count
            != expected_score_rows
            or self.score_models.aggregate_dixon_coles_metric.prediction_count
            != expected_score_rows
        ):
            msg = "advanced aggregate metrics do not cover the expected populations"
            raise ValueError(msg)
        expected_windows = walk_forward_windows()
        for score_report, window in zip(
            self.score_models.folds, expected_windows, strict=True
        ):
            if (
                score_report.partition_id != window.id
                or score_report.reference_season_ids != window.reference_season_ids
                or score_report.evaluation_season_id != window.evaluation_season_ids[0]
            ):
                msg = "score-model report contains an unsupported fold"
                raise ValueError(msg)
            expected_training_rows = sum(
                source_counts[season_id] for season_id in window.reference_season_ids
            )
            if (
                score_report.poisson_fit.training_row_count != expected_training_rows
                or score_report.dixon_coles_fit.training_row_count
                != expected_training_rows
                or score_report.poisson_metric.prediction_count
                != source_counts[score_report.evaluation_season_id]
            ):
                msg = "score-model fold counts do not match verified inputs"
                raise ValueError(msg)
        expected_calibration_windows = expected_windows[1:]
        for index, (calibration_fold_report, window) in enumerate(
            zip(self.calibration.folds, expected_calibration_windows, strict=True),
            start=1,
        ):
            expected_history = tuple(
                prior.evaluation_season_ids[0] for prior in expected_windows[:index]
            )
            expected_fit_count = sum(
                source_counts[season] for season in expected_history
            )
            if (
                calibration_fold_report.partition_id != window.id
                or calibration_fold_report.calibration_season_ids != expected_history
                or calibration_fold_report.evaluation_season_id
                != window.evaluation_season_ids[0]
                or calibration_fold_report.fit.training_prediction_count
                != expected_fit_count
                or calibration_fold_report.calibrated_metric.prediction_count
                != source_counts[calibration_fold_report.evaluation_season_id]
            ):
                msg = "calibration fold does not match the expanding OOF boundary"
                raise ValueError(msg)
        expected_development_rows = sum(
            source_counts[season] for season in DEVELOPMENT_SEASONS
        )
        if (
            self.score_models.final_poisson_fit.training_row_count
            != expected_development_rows
            or self.score_models.final_dixon_coles_fit.training_row_count
            != expected_development_rows
            or self.calibration.final_fit.training_prediction_count
            != self.source_catboost_tuning.selected_prediction_row_count
        ):
            msg = "final development fit counts do not match verified inputs"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class AdvancedEvaluationMaterializationResult:
    predictions_path: Path
    manifest_path: Path
    prediction_row_count: int
    predictions_sha256: str
    manifest_sha256: str
    calibration_strategy: str
    status: Literal["written", "already_current"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_model_bytes(model: BaseModel) -> bytes:
    return (
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _temperature_fit_report(fit: TemperatureFitDiagnostics) -> TemperatureFitReport:
    return TemperatureFitReport(**asdict(fit))


def _calibration_fold_report(fold: CalibrationFoldResult) -> CalibrationFoldReport:
    return CalibrationFoldReport(
        partition_id=fold.partition_id,
        calibration_season_ids=fold.calibration_season_ids,
        evaluation_season_id=fold.evaluation_season_id,
        fit=_temperature_fit_report(fold.fit),
        uncalibrated_metric=fold.uncalibrated_metric,
        calibrated_metric=fold.calibrated_metric,
    )


def _poisson_fit_report(fit: PoissonFitDiagnostics) -> PoissonFitReport:
    return PoissonFitReport(**asdict(fit))


def _dixon_coles_fit_report(fit: DixonColesFitDiagnostics) -> DixonColesFitReport:
    return DixonColesFitReport(**asdict(fit))


def _score_fold_report(fold: ScoreModelFoldResult) -> ScoreModelFoldReport:
    return ScoreModelFoldReport(
        partition_id=fold.partition_id,
        reference_season_ids=fold.reference_season_ids,
        evaluation_season_id=fold.evaluation_season_id,
        poisson_fit=_poisson_fit_report(fold.poisson_fit),
        dixon_coles_fit=_dixon_coles_fit_report(fold.dixon_coles_fit),
        poisson_metric=fold.poisson_metric,
        dixon_coles_metric=fold.dixon_coles_metric,
    )


def _stable_prediction_bytes(
    predictions: Sequence[ProbabilisticPrediction],
) -> bytes:
    method_order = {"catboost_calibrated": 0, "poisson": 1, "dixon_coles": 2}
    ordered = sorted(
        predictions,
        key=lambda prediction: (
            method_order.get(prediction.method, 99),
            prediction.partition_id,
            prediction.feature_cutoff_at,
            prediction.kickoff_at,
            prediction.source_training_example_id,
        ),
    )
    lines = (
        json.dumps(
            prediction.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for prediction in ordered
    )
    return ("\n".join(lines) + "\n").encode()


def _validate_predictions(
    predictions: Sequence[ProbabilisticPrediction],
    manifest: AdvancedEvaluationManifest,
) -> None:
    if len(predictions) != manifest.prediction_row_count:
        msg = "advanced prediction count does not match its manifest"
        raise AdvancedEvaluationError(msg)
    identities = tuple(prediction.id for prediction in predictions)
    if len(identities) != len(set(identities)):
        msg = "advanced prediction IDs must be unique"
        raise AdvancedEvaluationError(msg)
    expected_configurations = {
        "catboost_calibrated": CALIBRATION_CONFIGURATION_ID,
        "poisson": POISSON_CONFIGURATION_ID,
        "dixon_coles": DIXON_COLES_CONFIGURATION_ID,
    }
    windows_by_id = {window.id: window for window in walk_forward_windows()}
    method_counts: dict[str, int] = {method: 0 for method in expected_configurations}
    for prediction in predictions:
        expected_configuration = expected_configurations.get(prediction.method)
        window = windows_by_id.get(prediction.partition_id)
        if expected_configuration is None or window is None:
            msg = (
                f"advanced prediction {prediction.id} has an unsupported method or fold"
            )
            raise AdvancedEvaluationError(msg)
        if (
            prediction.configuration_id != expected_configuration
            or prediction.source_training_dataset_id
            != manifest.source_training_manifest.dataset_id
            or prediction.source_training_sha256
            != manifest.source_training_manifest.training_sha256
        ):
            msg = f"advanced prediction {prediction.id} has inconsistent lineage"
            raise AdvancedEvaluationError(msg)
        if (
            prediction.season_id not in window.evaluation_season_ids
            or prediction.season_id in manifest.untouched_test_season_ids
            or (
                prediction.method == "catboost_calibrated"
                and prediction.season_id not in CALIBRATION_EVALUATION_SEASONS
            )
        ):
            msg = (
                f"advanced prediction {prediction.id} is outside its temporal boundary"
            )
            raise AdvancedEvaluationError(msg)
        method_counts[prediction.method] += 1
    if (
        method_counts["catboost_calibrated"]
        != manifest.calibration.aggregate_calibrated_metric.prediction_count
        or method_counts["poisson"]
        != manifest.score_models.aggregate_poisson_metric.prediction_count
        or method_counts["dixon_coles"]
        != manifest.score_models.aggregate_dixon_coles_metric.prediction_count
    ):
        msg = "advanced prediction method counts do not match aggregate metrics"
        raise AdvancedEvaluationError(msg)


def write_advanced_evaluation_dataset(
    calibration: CalibrationEvaluationResult,
    score_models: ScoreModelEvaluationResult,
    output_directory: Path,
    source_training_manifest: TrainingDatasetManifest,
    source_training_manifest_sha256: str,
    source_catboost_tuning: CatBoostTuningSource,
) -> AdvancedEvaluationMaterializationResult:
    """Publish target-free predictions and strict Steps 3.6-3.8 lineage."""

    predictions = calibration.predictions + score_models.predictions
    prediction_payload = _stable_prediction_bytes(predictions)
    manifest = AdvancedEvaluationManifest(
        dataset_schema_version=ADVANCED_EVALUATION_SCHEMA_VERSION,
        dataset_id="advanced-evaluation-v1-2015-2016-to-2024-2025",
        competition_id="eng-premier-league",
        development_season_ids=DEVELOPMENT_SEASONS,
        untouched_test_season_ids=EXCLUDED_SEASONS,
        source_training_manifest_sha256=source_training_manifest_sha256,
        source_training_manifest=source_training_manifest,
        source_catboost_tuning=source_catboost_tuning,
        prediction_row_count=len(predictions),
        predictions_sha256=_sha256(prediction_payload),
        prediction_methods=("catboost_calibrated", "poisson", "dixon_coles"),
        predictions_ordered_by=(
            "method",
            "partition_id",
            "feature_cutoff_at",
            "kickoff_at",
            "training_example_id",
        ),
        calibration=CalibrationReport(
            method_version=CALIBRATION_METHOD_VERSION,
            configuration_id=CALIBRATION_CONFIGURATION_ID,
            protocol="expanding_prior_oof_temperature_scaling",
            parameters=calibration.parameters,
            folds=tuple(_calibration_fold_report(fold) for fold in calibration.folds),
            aggregate_uncalibrated_metric=calibration.aggregate_uncalibrated_metric,
            aggregate_calibrated_metric=calibration.aggregate_calibrated_metric,
            selection_rule="log_loss_then_brier_then_rps",
            selected_strategy=calibration.selected_strategy,
            final_fit=_temperature_fit_report(calibration.final_fit),
        ),
        score_models=ScoreModelReport(
            method_version=SCORE_MODEL_METHOD_VERSION,
            poisson_configuration_id=POISSON_CONFIGURATION_ID,
            dixon_coles_configuration_id=DIXON_COLES_CONFIGURATION_ID,
            predictor_contract=("canonical_team_ids_and_training_window_scores_only"),
            score_grid_maximum_goals_per_team=MAX_SCORE_GOALS,
            poisson_optimizer=PoissonOptimizerContract(
                optimizer_iterations=score_models.parameters.optimizer_iterations,
                learning_rate=score_models.parameters.learning_rate,
                beta_one=score_models.parameters.beta_one,
                beta_two=score_models.parameters.beta_two,
                epsilon=score_models.parameters.epsilon,
                l2_strength=score_models.parameters.l2_strength,
                minimum_expected_goals=(score_models.parameters.minimum_expected_goals),
                maximum_expected_goals=(score_models.parameters.maximum_expected_goals),
            ),
            dixon_coles_contract=DixonColesContract(
                fit="training_window_only_scalar_likelihood",
                optimizer_iterations=(
                    score_models.parameters.dixon_coles_optimizer_iterations
                ),
                rho_minimum=score_models.parameters.dixon_coles_rho_minimum,
                rho_maximum=score_models.parameters.dixon_coles_rho_maximum,
                adjusted_scores="0-0,0-1,1-0,1-1",
            ),
            folds=tuple(_score_fold_report(fold) for fold in score_models.folds),
            aggregate_poisson_metric=score_models.aggregate_poisson_metric,
            aggregate_dixon_coles_metric=score_models.aggregate_dixon_coles_metric,
            final_poisson_fit=_poisson_fit_report(score_models.final_poisson_fit),
            final_dixon_coles_fit=_dixon_coles_fit_report(
                score_models.final_dixon_coles_fit
            ),
        ),
    )
    _validate_predictions(predictions, manifest)
    manifest_payload = _stable_model_bytes(manifest)
    predictions_path = output_directory / "predictions.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"
    is_current = (
        predictions_path.exists()
        and manifest_path.exists()
        and predictions_path.read_bytes() == prediction_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(predictions_path, prediction_payload)
        _atomic_write(manifest_path, manifest_payload)
    return AdvancedEvaluationMaterializationResult(
        predictions_path=predictions_path,
        manifest_path=manifest_path,
        prediction_row_count=len(predictions),
        predictions_sha256=_sha256(prediction_payload),
        manifest_sha256=_sha256(manifest_payload),
        calibration_strategy=calibration.selected_strategy,
        status="already_current" if is_current else "written",
    )


def load_advanced_evaluation_dataset(
    predictions_path: Path,
    manifest_path: Path,
) -> tuple[tuple[ProbabilisticPrediction, ...], AdvancedEvaluationManifest]:
    """Load and strictly validate advanced development artifacts."""

    manifest_payload = manifest_path.read_bytes()
    manifest = AdvancedEvaluationManifest.model_validate_json(manifest_payload)
    if _stable_model_bytes(manifest) != manifest_payload:
        msg = "advanced evaluation manifest bytes are not deterministic"
        raise AdvancedEvaluationError(msg)
    prediction_payload = predictions_path.read_bytes()
    if _sha256(prediction_payload) != manifest.predictions_sha256:
        msg = "advanced prediction checksum does not match its manifest"
        raise AdvancedEvaluationError(msg)
    predictions = tuple(
        ProbabilisticPrediction.model_validate_json(line)
        for line in prediction_payload.decode().splitlines()
    )
    if _stable_prediction_bytes(predictions) != prediction_payload:
        msg = "advanced predictions are not deterministically ordered"
        raise AdvancedEvaluationError(msg)
    _validate_predictions(predictions, manifest)
    return predictions, manifest


def _catboost_source(
    manifest: CatBoostTuningDatasetManifest,
    manifest_sha256: str,
) -> CatBoostTuningSource:
    return CatBoostTuningSource(
        dataset_id=manifest.dataset_id,
        manifest_sha256=manifest_sha256,
        selected_candidate_id=manifest.selected_candidate_id,
        selected_prediction_row_count=manifest.selected_prediction_row_count,
        selected_predictions_sha256=manifest.selected_predictions_sha256,
        test_freeze_manifest_sha256=manifest.test_freeze_manifest_sha256,
    )


def materialize_advanced_evaluation(
    historical_manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> AdvancedEvaluationMaterializationResult:
    """Reverify raw lineage and run only development-time Steps 3.6-3.8."""

    training_result = materialize_training_dataset(
        historical_manifest_path,
        team_registry_path,
        season_registry_path,
        data_root,
    )
    examples, training_manifest = load_training_dataset(
        training_result.training_rows_path,
        training_result.manifest_path,
    )
    training_manifest_sha256 = _sha256(training_result.manifest_path.read_bytes())
    catboost_directory = (
        data_root
        / "processed"
        / "evaluation"
        / "epl"
        / "catboost-tuning-2015-2016_to_2024-2025"
    )
    catboost_predictions_path = catboost_directory / "selected-predictions.jsonl"
    catboost_manifest_path = catboost_directory / "dataset-manifest.json"
    catboost_predictions, catboost_manifest = load_catboost_tuning_dataset(
        catboost_predictions_path,
        catboost_manifest_path,
    )
    catboost_manifest_sha256 = _sha256(catboost_manifest_path.read_bytes())
    if (
        catboost_manifest.source_training_manifest != training_manifest
        or catboost_manifest.source_training_manifest_sha256 != training_manifest_sha256
    ):
        msg = "CatBoost tuning artifact does not match current verified training data"
        raise AdvancedEvaluationError(msg)
    freeze_path = (
        data_root
        / "processed"
        / "evaluation"
        / "epl"
        / "test-2025-2026"
        / "freeze-manifest.json"
    )
    freeze = load_test_freeze(freeze_path)
    if (
        freeze != catboost_manifest.test_freeze
        or _sha256(freeze_path.read_bytes())
        != catboost_manifest.test_freeze_manifest_sha256
    ):
        msg = "untouched test freeze does not match the CatBoost tuning lineage"
        raise AdvancedEvaluationError(msg)
    calibration = evaluate_expanding_temperature_calibration(
        catboost_predictions,
        examples,
    )
    score_models = evaluate_score_models_walk_forward(
        examples,
        source_training_dataset_id=training_manifest.dataset_id,
        source_training_sha256=training_manifest.training_sha256,
    )
    return write_advanced_evaluation_dataset(
        calibration,
        score_models,
        data_root
        / "processed"
        / "evaluation"
        / "epl"
        / "advanced-development-2015-2016_to_2024-2025",
        training_manifest,
        training_manifest_sha256,
        _catboost_source(catboost_manifest, catboost_manifest_sha256),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate calibration, Poisson and Dixon-Coles development models."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--seasons", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = materialize_advanced_evaluation(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    for field_name in ("predictions_path", "manifest_path"):
        serialized[field_name] = str(getattr(result, field_name))
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
