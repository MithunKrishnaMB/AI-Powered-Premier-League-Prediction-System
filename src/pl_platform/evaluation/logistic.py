"""Deterministic multinomial logistic regression for three-way outcomes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import log
from typing import Annotated, Final

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from pl_platform.domain.evaluation import OUTCOME_ORDER, OutcomeProbabilities
from pl_platform.domain.features import PredictorSet
from pl_platform.domain.training import TrainingExample

LOGISTIC_METHOD_VERSION: Final = 1
LOGISTIC_PREPROCESSOR_VERSION: Final = 1


class LogisticRegressionError(ValueError):
    """Training data or predictors violate the fixed logistic contract."""


class LogisticRegressionParameters(BaseModel):
    """Frozen optimizer and regularization settings; no tuning occurs here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    l2_strength: Annotated[float, Field(strict=True, gt=0.0)] = 1.0
    learning_rate: Annotated[float, Field(strict=True, gt=0.0)] = 0.02
    beta_one: Annotated[float, Field(strict=True, gt=0.0, lt=1.0)] = 0.9
    beta_two: Annotated[float, Field(strict=True, gt=0.0, lt=1.0)] = 0.999
    epsilon: Annotated[float, Field(strict=True, gt=0.0)] = 1e-8
    convergence_tolerance: Annotated[float, Field(strict=True, gt=0.0)] = 2e-7
    convergence_patience: Annotated[int, Field(strict=True, ge=1)] = 8
    maximum_iterations: Annotated[int, Field(strict=True, ge=1)] = 1200


DEFAULT_LOGISTIC_PARAMETERS = LogisticRegressionParameters()


@dataclass(frozen=True, slots=True)
class LogisticFitDiagnostics:
    iterations: int
    converged: bool
    final_objective: float
    predictor_count: int
    training_row_count: int


@dataclass(frozen=True, slots=True)
class FittedMultinomialLogisticRegression:
    """In-memory model; serialization belongs to the later registry milestone."""

    predictor_names: tuple[str, ...]
    imputation_means: npt.NDArray[np.float64]
    scaling_means: npt.NDArray[np.float64]
    scaling_scales: npt.NDArray[np.float64]
    coefficients: npt.NDArray[np.float64]
    intercepts: npt.NDArray[np.float64]
    diagnostics: LogisticFitDiagnostics

    def predict_probabilities(self, predictors: PredictorSet) -> OutcomeProbabilities:
        raw = predictor_matrix((predictors,), self.predictor_names)
        imputed = np.where(np.isnan(raw), self.imputation_means, raw)
        standardized = (imputed - self.scaling_means) / self.scaling_scales
        logits = standardized @ self.coefficients + self.intercepts
        probability_row = _softmax(logits)[0]
        home_win = round(float(probability_row[0]), 15)
        draw = round(float(probability_row[1]), 15)
        away_win = 1.0 - home_win - draw
        return OutcomeProbabilities(
            home_win=home_win,
            draw=draw,
            away_win=away_win,
        )


def predictor_matrix(
    predictor_sets: Sequence[PredictorSet],
    predictor_names: tuple[str, ...],
) -> npt.NDArray[np.float64]:
    if not predictor_names or predictor_names != tuple(sorted(set(predictor_names))):
        msg = "logistic predictor names must be non-empty, unique and ordered"
        raise LogisticRegressionError(msg)
    matrix = np.empty((len(predictor_sets), len(predictor_names)), dtype=np.float64)
    for row_index, predictors in enumerate(predictor_sets):
        if predictors.schema_id != "epl-pre-match" or predictors.schema_version != 2:
            msg = (
                "logistic regression requires predictor schema epl-pre-match version 2"
            )
            raise LogisticRegressionError(msg)
        names = tuple(item.name for item in predictors.values)
        if names != predictor_names:
            msg = "logistic predictor set does not match the declared ordered schema"
            raise LogisticRegressionError(msg)
        for column_index, item in enumerate(predictors.values):
            value = item.value
            if value is None:
                matrix[row_index, column_index] = np.nan
            elif type(value) is bool:
                matrix[row_index, column_index] = 1.0 if value else 0.0
            elif type(value) in (int, float):
                matrix[row_index, column_index] = float(value)
            else:  # pragma: no cover - PredictorSet rejects this before this boundary.
                msg = f"unsupported logistic predictor value for {item.name!r}"
                raise LogisticRegressionError(msg)
    return matrix


def _fit_preprocessor(
    raw: npt.NDArray[np.float64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    observed = ~np.isnan(raw)
    counts = observed.sum(axis=0)
    sums = np.where(observed, raw, 0.0).sum(axis=0)
    imputation_means = np.divide(
        sums,
        counts,
        out=np.zeros_like(sums),
        where=counts > 0,
    )
    imputed = np.where(observed, raw, imputation_means)
    scaling_means = imputed.mean(axis=0)
    variances = ((imputed - scaling_means) ** 2).mean(axis=0)
    scaling_scales = np.sqrt(variances)
    scaling_scales = np.where(scaling_scales > 1e-12, scaling_scales, 1.0)
    standardized = (imputed - scaling_means) / scaling_scales
    return standardized, imputation_means, scaling_means, scaling_scales


def _softmax(logits: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _objective(
    matrix: npt.NDArray[np.float64],
    targets: npt.NDArray[np.float64],
    coefficients: npt.NDArray[np.float64],
    intercepts: npt.NDArray[np.float64],
    l2_strength: float,
) -> float:
    probabilities = _softmax(matrix @ coefficients + intercepts)
    negative_log_likelihood = -float(
        np.sum(targets * np.log(probabilities)) / matrix.shape[0]
    )
    penalty = 0.5 * l2_strength * float(np.sum(coefficients**2)) / matrix.shape[0]
    return float(negative_log_likelihood + penalty)


def fit_multinomial_logistic_regression(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    parameters: LogisticRegressionParameters = DEFAULT_LOGISTIC_PARAMETERS,
) -> FittedMultinomialLogisticRegression:
    """Fit a full-batch, L2-regularized softmax regression without randomness."""

    if not examples:
        msg = "logistic regression requires training examples"
        raise LogisticRegressionError(msg)
    ordered_examples = tuple(
        sorted(examples, key=lambda item: (item.kickoff_at, item.id))
    )
    raw = predictor_matrix(
        tuple(example.predictors for example in ordered_examples),
        predictor_names,
    )
    matrix, imputation_means, scaling_means, scaling_scales = _fit_preprocessor(raw)
    outcome_index = {outcome: index for index, outcome in enumerate(OUTCOME_ORDER)}
    outcome_counts = Counter(example.target.outcome for example in ordered_examples)
    if any(outcome_counts[outcome] == 0 for outcome in OUTCOME_ORDER):
        msg = "logistic training window must contain every outcome"
        raise LogisticRegressionError(msg)
    target_indices = np.asarray(
        [outcome_index[example.target.outcome] for example in ordered_examples],
        dtype=np.int64,
    )
    targets = np.zeros((len(ordered_examples), len(OUTCOME_ORDER)), dtype=np.float64)
    targets[np.arange(len(ordered_examples)), target_indices] = 1.0

    coefficients = np.zeros(
        (len(predictor_names), len(OUTCOME_ORDER)), dtype=np.float64
    )
    intercepts = np.asarray(
        [
            log(outcome_counts[outcome] / len(ordered_examples))
            for outcome in OUTCOME_ORDER
        ],
        dtype=np.float64,
    )
    intercepts -= intercepts.mean()
    first_moment_coefficients = np.zeros_like(coefficients)
    second_moment_coefficients = np.zeros_like(coefficients)
    first_moment_intercepts = np.zeros_like(intercepts)
    second_moment_intercepts = np.zeros_like(intercepts)
    previous_objective = _objective(
        matrix,
        targets,
        coefficients,
        intercepts,
        parameters.l2_strength,
    )
    stable_iterations = 0
    converged = False
    completed_iterations = 0

    for iteration in range(1, parameters.maximum_iterations + 1):
        probabilities = _softmax(matrix @ coefficients + intercepts)
        errors = probabilities - targets
        coefficient_gradient = (matrix.T @ errors) / len(ordered_examples)
        coefficient_gradient += (
            parameters.l2_strength * coefficients / len(ordered_examples)
        )
        intercept_gradient = errors.mean(axis=0)

        first_moment_coefficients = (
            parameters.beta_one * first_moment_coefficients
            + (1.0 - parameters.beta_one) * coefficient_gradient
        )
        second_moment_coefficients = (
            parameters.beta_two * second_moment_coefficients
            + (1.0 - parameters.beta_two) * coefficient_gradient**2
        )
        first_moment_intercepts = (
            parameters.beta_one * first_moment_intercepts
            + (1.0 - parameters.beta_one) * intercept_gradient
        )
        second_moment_intercepts = (
            parameters.beta_two * second_moment_intercepts
            + (1.0 - parameters.beta_two) * intercept_gradient**2
        )
        beta_one_correction = 1.0 - parameters.beta_one**iteration
        beta_two_correction = 1.0 - parameters.beta_two**iteration
        coefficients -= (
            parameters.learning_rate
            * (first_moment_coefficients / beta_one_correction)
            / (
                np.sqrt(second_moment_coefficients / beta_two_correction)
                + parameters.epsilon
            )
        )
        intercepts -= (
            parameters.learning_rate
            * (first_moment_intercepts / beta_one_correction)
            / (
                np.sqrt(second_moment_intercepts / beta_two_correction)
                + parameters.epsilon
            )
        )
        coefficients -= coefficients.mean(axis=1, keepdims=True)
        intercepts -= intercepts.mean()

        current_objective = _objective(
            matrix,
            targets,
            coefficients,
            intercepts,
            parameters.l2_strength,
        )
        if abs(previous_objective - current_objective) <= (
            parameters.convergence_tolerance * max(1.0, abs(previous_objective))
        ):
            stable_iterations += 1
        else:
            stable_iterations = 0
        previous_objective = current_objective
        completed_iterations = iteration
        if stable_iterations >= parameters.convergence_patience:
            converged = True
            break

    return FittedMultinomialLogisticRegression(
        predictor_names=predictor_names,
        imputation_means=imputation_means,
        scaling_means=scaling_means,
        scaling_scales=scaling_scales,
        coefficients=coefficients,
        intercepts=intercepts,
        diagnostics=LogisticFitDiagnostics(
            iterations=completed_iterations,
            converged=converged,
            final_objective=previous_objective,
            predictor_count=len(predictor_names),
            training_row_count=len(ordered_examples),
        ),
    )
