"""Predefined CatBoost tuning over expanding chronological folds only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pl_platform.domain.evaluation import (
    ChronologicalEvaluationWindow,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.catboost_model import (
    CATBOOST_CANDIDATES,
    CATBOOST_METHOD_VERSION,
    CatBoostFitDiagnostics,
    CatBoostParameters,
    fit_catboost_classifier,
)
from pl_platform.evaluation.metrics import evaluate_probabilistic_predictions
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    examples_for_seasons,
    walk_forward_windows,
)


class CatBoostTuningError(ValueError):
    """CatBoost candidates or folds cannot form one deterministic comparison."""


@dataclass(frozen=True, slots=True)
class CatBoostFoldResult:
    window: ChronologicalEvaluationWindow
    fit: CatBoostFitDiagnostics
    predictions: tuple[ProbabilisticPrediction, ...]
    metric: ProbabilisticMetricSummary


@dataclass(frozen=True, slots=True)
class CatBoostCandidateResult:
    parameters: CatBoostParameters
    folds: tuple[CatBoostFoldResult, ...]
    aggregate_metric: ProbabilisticMetricSummary


@dataclass(frozen=True, slots=True)
class CatBoostTuningResult:
    candidates: tuple[CatBoostCandidateResult, ...]
    selected_candidate_id: str
    selected_predictions: tuple[ProbabilisticPrediction, ...]
    final_development_fit: CatBoostFitDiagnostics

    @property
    def selected_candidate(self) -> CatBoostCandidateResult:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.parameters.id == self.selected_candidate_id
        )


def _prediction(
    example: TrainingExample,
    *,
    probabilities: OutcomeProbabilities,
    candidate_id: str,
    partition_id: str,
    source_training_dataset_id: str,
    source_training_sha256: str,
) -> ProbabilisticPrediction:
    payload = {
        "id": deterministic_prediction_id(
            source_training_sha256=source_training_sha256,
            source_training_example_id=example.id,
            partition_id=partition_id,
            method="catboost",
            method_version=CATBOOST_METHOD_VERSION,
            configuration_id=candidate_id,
        ),
        "method": "catboost",
        "method_version": CATBOOST_METHOD_VERSION,
        "configuration_id": candidate_id,
        "partition_id": partition_id,
        "source_training_dataset_id": source_training_dataset_id,
        "source_training_sha256": source_training_sha256,
        "source_training_example_id": example.id,
        "fixture_id": example.fixture_id,
        "season_id": example.season_id,
        "kickoff_at": example.kickoff_at,
        "feature_cutoff_at": example.feature_cutoff_at,
        "probabilities": probabilities,
    }
    return ProbabilisticPrediction.model_validate(payload)


def _evaluate_candidate(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    parameters: CatBoostParameters,
    *,
    source_training_dataset_id: str,
    source_training_sha256: str,
) -> CatBoostCandidateResult:
    folds: list[CatBoostFoldResult] = []
    for window in walk_forward_windows():
        reference = examples_for_seasons(examples, window.reference_season_ids)
        evaluation = examples_for_seasons(examples, window.evaluation_season_ids)
        model = fit_catboost_classifier(reference, predictor_names, parameters)
        predictions = tuple(
            _prediction(
                example,
                probabilities=model.predict_probabilities(example.predictors),
                candidate_id=parameters.id,
                partition_id=window.id,
                source_training_dataset_id=source_training_dataset_id,
                source_training_sha256=source_training_sha256,
            )
            for example in evaluation
        )
        actual = {example.id: example.target.outcome for example in evaluation}
        metric = evaluate_probabilistic_predictions(predictions, actual)
        folds.append(
            CatBoostFoldResult(
                window=window,
                fit=model.diagnostics,
                predictions=predictions,
                metric=metric,
            )
        )

    all_predictions = tuple(
        prediction for fold in folds for prediction in fold.predictions
    )
    evaluation_seasons = tuple(
        window.evaluation_season_ids[0] for window in walk_forward_windows()
    )
    evaluation_examples = examples_for_seasons(examples, evaluation_seasons)
    actual = {example.id: example.target.outcome for example in evaluation_examples}
    return CatBoostCandidateResult(
        parameters=parameters,
        folds=tuple(folds),
        aggregate_metric=evaluate_probabilistic_predictions(
            all_predictions,
            actual,
        ),
    )


def tune_catboost_with_walk_forward(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    *,
    source_training_dataset_id: str,
    source_training_sha256: str,
    candidates: tuple[CatBoostParameters, ...] = CATBOOST_CANDIDATES,
) -> CatBoostTuningResult:
    """Select a fixed candidate by walk-forward log loss, never test data."""

    if not candidates:
        msg = "CatBoost tuning requires at least one predefined candidate"
        raise CatBoostTuningError(msg)
    candidate_ids = tuple(candidate.id for candidate in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        msg = "CatBoost candidate IDs must be unique"
        raise CatBoostTuningError(msg)
    results = tuple(
        _evaluate_candidate(
            examples,
            predictor_names,
            candidate,
            source_training_dataset_id=source_training_dataset_id,
            source_training_sha256=source_training_sha256,
        )
        for candidate in candidates
    )
    selected = min(
        results,
        key=lambda result: (
            result.aggregate_metric.mean_log_loss,
            result.aggregate_metric.mean_multiclass_brier_score,
            result.aggregate_metric.mean_ranked_probability_score,
            result.parameters.id,
        ),
    )
    development_examples = examples_for_seasons(examples, DEVELOPMENT_SEASONS)
    final_model = fit_catboost_classifier(
        development_examples,
        predictor_names,
        selected.parameters,
    )
    return CatBoostTuningResult(
        candidates=results,
        selected_candidate_id=selected.parameters.id,
        selected_predictions=tuple(
            prediction for fold in selected.folds for prediction in fold.predictions
        ),
        final_development_fit=final_model.diagnostics,
    )
