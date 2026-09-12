"""Leakage-safe temperature calibration over prior out-of-fold predictions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import exp, log
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import (
    OUTCOME_ORDER,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.metrics import evaluate_probabilistic_predictions
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    walk_forward_windows,
)

CALIBRATION_METHOD_VERSION: Final = 1
CALIBRATION_CONFIGURATION_ID: Final = "temperature-scaling-v1"
CALIBRATION_EVALUATION_SEASONS: Final = DEVELOPMENT_SEASONS[6:]


class CalibrationError(ValueError):
    """Calibration inputs violate the chronological out-of-fold contract."""


class TemperatureCalibrationParameters(BaseModel):
    """Frozen bounded scalar optimizer contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_temperature: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ] = 0.25
    maximum_temperature: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ] = 4.0
    optimizer_iterations: Literal[96] = 96
    probability_floor: Annotated[
        float, Field(strict=True, gt=0.0, lt=1.0 / 3.0, allow_inf_nan=False)
    ] = 1e-15

    @model_validator(mode="after")
    def bounds_must_be_ordered(self) -> Self:
        if self.minimum_temperature >= self.maximum_temperature:
            msg = "temperature bounds must be strictly ordered"
            raise ValueError(msg)
        return self


DEFAULT_CALIBRATION_PARAMETERS: Final = TemperatureCalibrationParameters()


@dataclass(frozen=True, slots=True)
class TemperatureFitDiagnostics:
    temperature: float
    training_prediction_count: int
    training_log_loss_before: float
    training_log_loss_after: float


@dataclass(frozen=True, slots=True)
class CalibrationFoldResult:
    partition_id: str
    calibration_season_ids: tuple[str, ...]
    evaluation_season_id: str
    fit: TemperatureFitDiagnostics
    uncalibrated_metric: ProbabilisticMetricSummary
    calibrated_metric: ProbabilisticMetricSummary
    predictions: tuple[ProbabilisticPrediction, ...]


@dataclass(frozen=True, slots=True)
class CalibrationEvaluationResult:
    parameters: TemperatureCalibrationParameters
    folds: tuple[CalibrationFoldResult, ...]
    aggregate_uncalibrated_metric: ProbabilisticMetricSummary
    aggregate_calibrated_metric: ProbabilisticMetricSummary
    selected_strategy: Literal["identity", "temperature_scaling"]
    final_fit: TemperatureFitDiagnostics

    @property
    def predictions(self) -> tuple[ProbabilisticPrediction, ...]:
        return tuple(
            prediction for fold in self.folds for prediction in fold.predictions
        )


def temperature_scaled_probabilities(
    probabilities: OutcomeProbabilities,
    temperature: float,
    *,
    probability_floor: float = 1e-15,
) -> OutcomeProbabilities:
    """Apply one positive temperature to a three-way probability vector."""

    if not 0.0 < temperature < float("inf"):
        msg = "calibration temperature must be positive and finite"
        raise CalibrationError(msg)
    if not 0.0 < probability_floor < 1.0 / 3.0:
        msg = "calibration probability floor is invalid"
        raise CalibrationError(msg)
    raw = tuple(probabilities.for_outcome(outcome) for outcome in OUTCOME_ORDER)
    logits = tuple(log(max(value, probability_floor)) / temperature for value in raw)
    offset = max(logits)
    weights = tuple(exp(value - offset) for value in logits)
    denominator = sum(weights)
    home_win = round(weights[0] / denominator, 15)
    draw = round(weights[1] / denominator, 15)
    return OutcomeProbabilities(
        home_win=home_win,
        draw=draw,
        away_win=1.0 - home_win - draw,
    )


def _mean_log_loss(
    predictions: Sequence[ProbabilisticPrediction],
    actual_outcomes: Mapping[UUID, MatchOutcome],
    temperature: float,
    probability_floor: float,
) -> float:
    losses = []
    for prediction in predictions:
        actual = actual_outcomes.get(prediction.source_training_example_id)
        if actual is None:
            msg = "calibration target population does not match predictions"
            raise CalibrationError(msg)
        calibrated = temperature_scaled_probabilities(
            prediction.probabilities,
            temperature,
            probability_floor=probability_floor,
        )
        losses.append(-log(max(calibrated.for_outcome(actual), probability_floor)))
    if not losses:
        msg = "temperature calibration requires predictions"
        raise CalibrationError(msg)
    return sum(losses) / len(losses)


def fit_temperature_scaling(
    predictions: Sequence[ProbabilisticPrediction],
    actual_outcomes: Mapping[UUID, MatchOutcome],
    parameters: TemperatureCalibrationParameters = DEFAULT_CALIBRATION_PARAMETERS,
) -> TemperatureFitDiagnostics:
    """Fit a scalar temperature with a deterministic golden-section search."""

    ordered_predictions = tuple(
        sorted(
            predictions, key=lambda prediction: prediction.source_training_example_id
        )
    )
    identities = tuple(
        prediction.source_training_example_id for prediction in ordered_predictions
    )
    if len(identities) != len(set(identities)):
        msg = "calibration predictions must reference unique examples"
        raise CalibrationError(msg)
    if set(identities) != set(actual_outcomes):
        msg = "calibration prediction and target populations must match"
        raise CalibrationError(msg)
    lower = log(parameters.minimum_temperature)
    upper = log(parameters.maximum_temperature)
    ratio = (5.0**0.5 - 1.0) / 2.0
    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)

    def objective(log_temperature: float) -> float:
        # The sorted order keeps floating-point reduction deterministic.
        return _mean_log_loss(
            ordered_predictions,
            actual_outcomes,
            exp(log_temperature),
            parameters.probability_floor,
        )

    left_value = objective(left)
    right_value = objective(right)
    for _ in range(parameters.optimizer_iterations):
        if left_value <= right_value:
            upper = right
            right = left
            right_value = left_value
            left = upper - ratio * (upper - lower)
            left_value = objective(left)
        else:
            lower = left
            left = right
            left_value = right_value
            right = lower + ratio * (upper - lower)
            right_value = objective(right)
    temperature = exp((lower + upper) / 2.0)
    return TemperatureFitDiagnostics(
        temperature=temperature,
        training_prediction_count=len(ordered_predictions),
        training_log_loss_before=objective(0.0),
        training_log_loss_after=objective(log(temperature)),
    )


def _calibrated_prediction(
    source: ProbabilisticPrediction,
    temperature: float,
) -> ProbabilisticPrediction:
    return ProbabilisticPrediction(
        id=deterministic_prediction_id(
            source_training_sha256=source.source_training_sha256,
            source_training_example_id=source.source_training_example_id,
            partition_id=source.partition_id,
            method="catboost_calibrated",
            method_version=CALIBRATION_METHOD_VERSION,
            configuration_id=CALIBRATION_CONFIGURATION_ID,
        ),
        method="catboost_calibrated",
        method_version=CALIBRATION_METHOD_VERSION,
        configuration_id=CALIBRATION_CONFIGURATION_ID,
        partition_id=source.partition_id,
        source_training_dataset_id=source.source_training_dataset_id,
        source_training_sha256=source.source_training_sha256,
        source_training_example_id=source.source_training_example_id,
        fixture_id=source.fixture_id,
        season_id=source.season_id,
        kickoff_at=source.kickoff_at,
        feature_cutoff_at=source.feature_cutoff_at,
        probabilities=temperature_scaled_probabilities(
            source.probabilities,
            temperature,
        ),
    )


def evaluate_expanding_temperature_calibration(
    source_predictions: Sequence[ProbabilisticPrediction],
    examples: Sequence[TrainingExample],
    parameters: TemperatureCalibrationParameters = DEFAULT_CALIBRATION_PARAMETERS,
) -> CalibrationEvaluationResult:
    """Fit on prior OOF seasons and apply to each next development season."""

    if not source_predictions:
        msg = "calibration requires source predictions"
        raise CalibrationError(msg)
    if {prediction.method for prediction in source_predictions} != {"catboost"}:
        msg = "temperature calibration requires CatBoost source predictions"
        raise CalibrationError(msg)
    configurations = {prediction.configuration_id for prediction in source_predictions}
    if len(configurations) != 1 or None in configurations:
        msg = "calibration requires one explicit CatBoost configuration"
        raise CalibrationError(msg)
    if any(
        prediction.season_id not in DEVELOPMENT_SEASONS
        for prediction in source_predictions
    ):
        msg = "calibration cannot consume the untouched test season"
        raise CalibrationError(msg)
    ordered_source_predictions = tuple(
        sorted(
            source_predictions,
            key=lambda prediction: (
                prediction.partition_id,
                prediction.feature_cutoff_at,
                prediction.kickoff_at,
                prediction.source_training_example_id,
            ),
        )
    )

    outcomes = {
        example.id: example.target.outcome
        for example in examples
        if example.season_id in DEVELOPMENT_SEASONS
    }
    windows = walk_forward_windows()
    source_identities = tuple(
        prediction.source_training_example_id
        for prediction in ordered_source_predictions
    )
    expected_identities = {
        example.id
        for example in examples
        if example.season_id
        in tuple(window.evaluation_season_ids[0] for window in windows)
    }
    if (
        len(source_identities) != len(set(source_identities))
        or set(source_identities) != expected_identities
    ):
        msg = "CatBoost calibration source population is incomplete or duplicated"
        raise CalibrationError(msg)
    window_by_id = {window.id: window for window in windows}
    if any(
        prediction.partition_id not in window_by_id
        or prediction.season_id
        not in window_by_id[prediction.partition_id].evaluation_season_ids
        for prediction in ordered_source_predictions
    ):
        msg = "CatBoost calibration source violates its walk-forward fold"
        raise CalibrationError(msg)
    by_partition = {
        window.id: tuple(
            prediction
            for prediction in ordered_source_predictions
            if prediction.partition_id == window.id
        )
        for window in windows
    }
    folds: list[CalibrationFoldResult] = []
    for index in range(1, len(windows)):
        evaluation_window = windows[index]
        reference_predictions = tuple(
            prediction
            for window in windows[:index]
            for prediction in by_partition[window.id]
        )
        evaluation_predictions = by_partition[evaluation_window.id]
        reference_outcomes = {
            prediction.source_training_example_id: outcomes[
                prediction.source_training_example_id
            ]
            for prediction in reference_predictions
        }
        evaluation_outcomes = {
            prediction.source_training_example_id: outcomes[
                prediction.source_training_example_id
            ]
            for prediction in evaluation_predictions
        }
        fit = fit_temperature_scaling(
            reference_predictions,
            reference_outcomes,
            parameters,
        )
        calibrated = tuple(
            _calibrated_prediction(prediction, fit.temperature)
            for prediction in evaluation_predictions
        )
        folds.append(
            CalibrationFoldResult(
                partition_id=evaluation_window.id,
                calibration_season_ids=tuple(
                    window.evaluation_season_ids[0] for window in windows[:index]
                ),
                evaluation_season_id=evaluation_window.evaluation_season_ids[0],
                fit=fit,
                uncalibrated_metric=evaluate_probabilistic_predictions(
                    evaluation_predictions,
                    evaluation_outcomes,
                ),
                calibrated_metric=evaluate_probabilistic_predictions(
                    calibrated,
                    evaluation_outcomes,
                ),
                predictions=calibrated,
            )
        )

    paired_source = tuple(
        prediction for fold in folds for prediction in by_partition[fold.partition_id]
    )
    calibrated_predictions = tuple(
        prediction for fold in folds for prediction in fold.predictions
    )
    paired_outcomes = {
        prediction.source_training_example_id: outcomes[
            prediction.source_training_example_id
        ]
        for prediction in paired_source
    }
    uncalibrated_metric = evaluate_probabilistic_predictions(
        paired_source,
        paired_outcomes,
    )
    calibrated_metric = evaluate_probabilistic_predictions(
        calibrated_predictions,
        paired_outcomes,
    )

    def metric_key(metric: ProbabilisticMetricSummary) -> tuple[float, float, float]:
        return (
            metric.mean_log_loss,
            metric.mean_multiclass_brier_score,
            metric.mean_ranked_probability_score,
        )

    selected_strategy: Literal["identity", "temperature_scaling"] = (
        "temperature_scaling"
        if metric_key(calibrated_metric) < metric_key(uncalibrated_metric)
        else "identity"
    )
    all_outcomes = {
        prediction.source_training_example_id: outcomes[
            prediction.source_training_example_id
        ]
        for prediction in ordered_source_predictions
    }
    final_fit = fit_temperature_scaling(
        ordered_source_predictions,
        all_outcomes,
        parameters,
    )
    return CalibrationEvaluationResult(
        parameters=parameters,
        folds=tuple(folds),
        aggregate_uncalibrated_metric=uncalibrated_metric,
        aggregate_calibrated_metric=calibrated_metric,
        selected_strategy=selected_strategy,
        final_fit=final_fit,
    )
