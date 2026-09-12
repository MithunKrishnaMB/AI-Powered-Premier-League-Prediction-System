"""Fixed holdout and expanding-season walk-forward evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pl_platform.domain.evaluation import (
    ChronologicalEvaluationWindow,
    EvaluationMethod,
    OutcomeCounts,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.benchmarks import (
    BENCHMARK_METHOD_VERSION,
    elo_benchmark_probabilities,
    fit_naive_outcome_prior,
)
from pl_platform.evaluation.logistic import (
    DEFAULT_LOGISTIC_PARAMETERS,
    LOGISTIC_METHOD_VERSION,
    LogisticFitDiagnostics,
    LogisticRegressionParameters,
    fit_multinomial_logistic_regression,
)
from pl_platform.evaluation.metrics import evaluate_probabilistic_predictions

DEVELOPMENT_SEASONS: Final = (
    "2015-2016",
    "2016-2017",
    "2017-2018",
    "2018-2019",
    "2019-2020",
    "2020-2021",
    "2021-2022",
    "2022-2023",
    "2023-2024",
    "2024-2025",
)
EXCLUDED_SEASONS: Final = ("2025-2026",)
EXPECTED_INPUT_SEASONS: Final = DEVELOPMENT_SEASONS + EXCLUDED_SEASONS
HOLDOUT_WINDOW: Final = ChronologicalEvaluationWindow(
    id="step-3-1-holdout",
    reference_season_ids=DEVELOPMENT_SEASONS[:8],
    evaluation_season_ids=DEVELOPMENT_SEASONS[8:],
    excluded_season_ids=EXCLUDED_SEASONS,
)
WALK_FORWARD_INITIAL_TRAINING_SEASONS: Final = 5


class WalkForwardError(ValueError):
    """The combined corpus cannot satisfy the fixed chronological plan."""


@dataclass(frozen=True, slots=True)
class EvaluationPartitionResult:
    window: ChronologicalEvaluationWindow
    reference_row_count: int
    evaluation_row_count: int
    naive_reference_counts: OutcomeCounts
    naive_prior: OutcomeProbabilities
    logistic_fit: LogisticFitDiagnostics
    predictions: tuple[ProbabilisticPrediction, ...]
    metrics: tuple[ProbabilisticMetricSummary, ...]


@dataclass(frozen=True, slots=True)
class CompleteEvaluationResult:
    logistic_parameters: LogisticRegressionParameters
    holdout: EvaluationPartitionResult
    walk_forward_folds: tuple[EvaluationPartitionResult, ...]
    walk_forward_aggregate_metrics: tuple[ProbabilisticMetricSummary, ...]

    @property
    def predictions(self) -> tuple[ProbabilisticPrediction, ...]:
        return self.holdout.predictions + tuple(
            prediction
            for fold in self.walk_forward_folds
            for prediction in fold.predictions
        )


def _examples_for_seasons(
    examples: Sequence[TrainingExample],
    season_ids: tuple[str, ...],
) -> tuple[TrainingExample, ...]:
    selected = tuple(example for example in examples if example.season_id in season_ids)
    if {example.season_id for example in selected} != set(season_ids):
        msg = "evaluation corpus does not cover every requested season"
        raise WalkForwardError(msg)
    return tuple(
        sorted(
            selected,
            key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
        )
    )


def _prediction(
    example: TrainingExample,
    probabilities: OutcomeProbabilities,
    *,
    method: EvaluationMethod,
    partition_id: str,
    source_training_dataset_id: str,
    source_training_sha256: str,
) -> ProbabilisticPrediction:
    method_version = (
        LOGISTIC_METHOD_VERSION
        if method == "multinomial_logistic"
        else BENCHMARK_METHOD_VERSION
    )
    payload = {
        "id": deterministic_prediction_id(
            source_training_sha256=source_training_sha256,
            source_training_example_id=example.id,
            partition_id=partition_id,
            method=method,
            method_version=method_version,
        ),
        "method": method,
        "method_version": method_version,
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


def evaluate_partition(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    window: ChronologicalEvaluationWindow,
    *,
    source_training_dataset_id: str,
    source_training_sha256: str,
    logistic_parameters: LogisticRegressionParameters = DEFAULT_LOGISTIC_PARAMETERS,
) -> EvaluationPartitionResult:
    """Fit on reference seasons and evaluate all methods on later seasons."""

    reference = _examples_for_seasons(examples, window.reference_season_ids)
    evaluation = _examples_for_seasons(examples, window.evaluation_season_ids)
    if max(item.kickoff_at for item in reference) >= min(
        item.feature_cutoff_at for item in evaluation
    ):
        msg = "reference examples must occur before the evaluation boundary"
        raise WalkForwardError(msg)
    reference_ids = {item.id for item in reference}
    evaluation_ids = {item.id for item in evaluation}
    if reference_ids & evaluation_ids:
        msg = "reference and evaluation examples must be disjoint"
        raise WalkForwardError(msg)

    reference_counts, naive_prior = fit_naive_outcome_prior(
        tuple(item.target for item in reference)
    )
    logistic_model = fit_multinomial_logistic_regression(
        reference,
        predictor_names,
        logistic_parameters,
    )
    if not logistic_model.diagnostics.converged:
        msg = f"logistic regression did not converge for partition {window.id!r}"
        raise WalkForwardError(msg)
    by_method: dict[EvaluationMethod, list[ProbabilisticPrediction]] = {
        "naive": [],
        "elo": [],
        "multinomial_logistic": [],
    }
    for example in evaluation:
        method_probabilities: dict[EvaluationMethod, OutcomeProbabilities] = {
            "naive": naive_prior,
            "elo": elo_benchmark_probabilities(
                example.predictors,
                draw_probability=naive_prior.draw,
            ),
            "multinomial_logistic": logistic_model.predict_probabilities(
                example.predictors
            ),
        }
        for method, probabilities in method_probabilities.items():
            by_method[method].append(
                _prediction(
                    example,
                    probabilities,
                    method=method,
                    partition_id=window.id,
                    source_training_dataset_id=source_training_dataset_id,
                    source_training_sha256=source_training_sha256,
                )
            )

    actual_outcomes = {item.id: item.target.outcome for item in evaluation}
    metrics = tuple(
        evaluate_probabilistic_predictions(by_method[method], actual_outcomes)
        for method in ("naive", "elo", "multinomial_logistic")
    )
    predictions = tuple(
        sorted(
            (prediction for values in by_method.values() for prediction in values),
            key=lambda item: (
                item.feature_cutoff_at,
                item.kickoff_at,
                item.source_training_example_id,
                item.method,
            ),
        )
    )
    return EvaluationPartitionResult(
        window=window,
        reference_row_count=len(reference),
        evaluation_row_count=len(evaluation),
        naive_reference_counts=reference_counts,
        naive_prior=naive_prior,
        logistic_fit=logistic_model.diagnostics,
        predictions=predictions,
        metrics=metrics,
    )


def walk_forward_windows() -> tuple[ChronologicalEvaluationWindow, ...]:
    """Return five expanding folds, each evaluating one complete season."""

    return tuple(
        ChronologicalEvaluationWindow(
            id=f"walk-forward-{DEVELOPMENT_SEASONS[index]}",
            reference_season_ids=DEVELOPMENT_SEASONS[:index],
            evaluation_season_ids=(DEVELOPMENT_SEASONS[index],),
            excluded_season_ids=DEVELOPMENT_SEASONS[index + 1 :] + EXCLUDED_SEASONS,
        )
        for index in range(
            WALK_FORWARD_INITIAL_TRAINING_SEASONS,
            len(DEVELOPMENT_SEASONS),
        )
    )


def evaluate_holdout_and_walk_forward(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    *,
    source_training_dataset_id: str,
    source_training_sha256: str,
    logistic_parameters: LogisticRegressionParameters = DEFAULT_LOGISTIC_PARAMETERS,
) -> CompleteEvaluationResult:
    """Run the fixed Steps 3.1-3.3 development evaluation contract."""

    available_seasons = tuple(sorted({example.season_id for example in examples}))
    if available_seasons != EXPECTED_INPUT_SEASONS:
        msg = "evaluation requires the complete 2015-2016 through 2025-2026 corpus"
        raise WalkForwardError(msg)
    holdout = evaluate_partition(
        examples,
        predictor_names,
        HOLDOUT_WINDOW,
        source_training_dataset_id=source_training_dataset_id,
        source_training_sha256=source_training_sha256,
        logistic_parameters=logistic_parameters,
    )
    folds = tuple(
        evaluate_partition(
            examples,
            predictor_names,
            window,
            source_training_dataset_id=source_training_dataset_id,
            source_training_sha256=source_training_sha256,
            logistic_parameters=logistic_parameters,
        )
        for window in walk_forward_windows()
    )
    aggregate_metrics: list[ProbabilisticMetricSummary] = []
    evaluation_examples = _examples_for_seasons(
        examples,
        tuple(window.evaluation_season_ids[0] for window in walk_forward_windows()),
    )
    actual_outcomes = {item.id: item.target.outcome for item in evaluation_examples}
    methods: tuple[EvaluationMethod, ...] = (
        "naive",
        "elo",
        "multinomial_logistic",
    )
    for method in methods:
        predictions = tuple(
            prediction
            for fold in folds
            for prediction in fold.predictions
            if prediction.method == method
        )
        aggregate_metrics.append(
            evaluate_probabilistic_predictions(
                predictions,
                actual_outcomes,
            )
        )
    return CompleteEvaluationResult(
        logistic_parameters=logistic_parameters,
        holdout=holdout,
        walk_forward_folds=folds,
        walk_forward_aggregate_metrics=tuple(aggregate_metrics),
    )
