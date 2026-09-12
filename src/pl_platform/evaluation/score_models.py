"""Deterministic independent-Poisson score model and Dixon-Coles correction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Annotated, Final, Literal, Self
from uuid import UUID

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import (
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.metrics import evaluate_probabilistic_predictions
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    EXPECTED_INPUT_SEASONS,
    examples_for_seasons,
    walk_forward_windows,
)

SCORE_MODEL_METHOD_VERSION: Final = 1
POISSON_CONFIGURATION_ID: Final = "independent-poisson-v1"
DIXON_COLES_CONFIGURATION_ID: Final = "dixon-coles-v1"
MAX_SCORE_GOALS: Final = 40
MIN_EXPECTED_GOALS: Final = 0.05
MAX_EXPECTED_GOALS: Final = 6.0
DIXON_COLES_RHO_MIN: Final = -0.15
DIXON_COLES_RHO_MAX: Final = 0.025


class ScoreModelError(ValueError):
    """Score-model data, fit or probability output is invalid."""


class PoissonModelParameters(BaseModel):
    """Frozen full-batch optimizer and regularization contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    optimizer_iterations: Annotated[int, Field(strict=True, ge=1)] = 2_000
    learning_rate: Annotated[
        float, Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False)
    ] = 0.03
    beta_one: Annotated[
        float, Field(strict=True, gt=0.0, lt=1.0, allow_inf_nan=False)
    ] = 0.9
    beta_two: Annotated[
        float, Field(strict=True, gt=0.0, lt=1.0, allow_inf_nan=False)
    ] = 0.999
    epsilon: Annotated[float, Field(strict=True, gt=0.0, allow_inf_nan=False)] = 1e-8
    l2_strength: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)] = (
        0.01
    )
    minimum_expected_goals: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ] = MIN_EXPECTED_GOALS
    maximum_expected_goals: Annotated[
        float, Field(strict=True, gt=0.0, allow_inf_nan=False)
    ] = MAX_EXPECTED_GOALS
    maximum_score_goals: Annotated[int, Field(strict=True, ge=1, le=100)] = (
        MAX_SCORE_GOALS
    )
    dixon_coles_optimizer_iterations: Annotated[int, Field(strict=True, ge=1)] = 96
    dixon_coles_rho_minimum: Annotated[
        float, Field(strict=True, ge=-0.15, le=0.025, allow_inf_nan=False)
    ] = DIXON_COLES_RHO_MIN
    dixon_coles_rho_maximum: Annotated[
        float, Field(strict=True, ge=-0.15, le=0.025, allow_inf_nan=False)
    ] = DIXON_COLES_RHO_MAX

    @model_validator(mode="after")
    def bounds_must_be_safe_and_ordered(self) -> Self:
        if self.minimum_expected_goals >= self.maximum_expected_goals:
            msg = "Poisson expected-goal bounds must be strictly ordered"
            raise ValueError(msg)
        if self.dixon_coles_rho_minimum >= self.dixon_coles_rho_maximum:
            msg = "Dixon-Coles rho bounds must be strictly ordered"
            raise ValueError(msg)
        if (
            1.0 + self.maximum_expected_goals * self.dixon_coles_rho_minimum <= 0.0
            or 1.0 - self.maximum_expected_goals**2 * self.dixon_coles_rho_maximum
            <= 0.0
        ):
            msg = "Dixon-Coles rho bounds are unsafe for the expected-goal cap"
            raise ValueError(msg)
        return self


DEFAULT_POISSON_PARAMETERS: Final = PoissonModelParameters()


@dataclass(frozen=True, slots=True)
class PoissonFitDiagnostics:
    training_row_count: int
    team_count: int
    optimizer_iterations: int
    final_objective: float
    mean_home_goals: float
    mean_away_goals: float


@dataclass(frozen=True, slots=True)
class DixonColesFitDiagnostics:
    training_row_count: int
    rho: float
    low_score_row_count: int
    adjustment_negative_log_likelihood: float


@dataclass(frozen=True, slots=True)
class FittedIndependentPoisson:
    """In-memory team attack/defence score model."""

    team_ids: tuple[UUID, ...]
    intercept: float
    home_advantage: float
    attack: npt.NDArray[np.float64]
    defence: npt.NDArray[np.float64]
    parameters: PoissonModelParameters
    diagnostics: PoissonFitDiagnostics

    def expected_goals(self, example: TrainingExample) -> tuple[float, float]:
        team_index = {team_id: index for index, team_id in enumerate(self.team_ids)}
        home_index = team_index.get(example.home_team_id)
        away_index = team_index.get(example.away_team_id)
        home_attack = 0.0 if home_index is None else float(self.attack[home_index])
        home_defence = 0.0 if home_index is None else float(self.defence[home_index])
        away_attack = 0.0 if away_index is None else float(self.attack[away_index])
        away_defence = 0.0 if away_index is None else float(self.defence[away_index])
        home_log_rate = (
            self.intercept + self.home_advantage + home_attack + away_defence
        )
        away_log_rate = self.intercept + away_attack + home_defence
        lower = log(self.parameters.minimum_expected_goals)
        upper = log(self.parameters.maximum_expected_goals)
        return (
            exp(min(max(home_log_rate, lower), upper)),
            exp(min(max(away_log_rate, lower), upper)),
        )

    def probabilities(self, example: TrainingExample) -> OutcomeProbabilities:
        home_rate, away_rate = self.expected_goals(example)
        return poisson_outcome_probabilities(
            home_rate,
            away_rate,
            max_goals=self.parameters.maximum_score_goals,
        )


@dataclass(frozen=True, slots=True)
class ScoreModelFoldResult:
    partition_id: str
    reference_season_ids: tuple[str, ...]
    evaluation_season_id: str
    poisson_fit: PoissonFitDiagnostics
    dixon_coles_fit: DixonColesFitDiagnostics
    poisson_predictions: tuple[ProbabilisticPrediction, ...]
    dixon_coles_predictions: tuple[ProbabilisticPrediction, ...]
    poisson_metric: ProbabilisticMetricSummary
    dixon_coles_metric: ProbabilisticMetricSummary


@dataclass(frozen=True, slots=True)
class ScoreModelEvaluationResult:
    parameters: PoissonModelParameters
    folds: tuple[ScoreModelFoldResult, ...]
    aggregate_poisson_metric: ProbabilisticMetricSummary
    aggregate_dixon_coles_metric: ProbabilisticMetricSummary
    final_poisson_fit: PoissonFitDiagnostics
    final_dixon_coles_fit: DixonColesFitDiagnostics

    @property
    def predictions(self) -> tuple[ProbabilisticPrediction, ...]:
        return tuple(
            prediction
            for fold in self.folds
            for predictions in (
                fold.poisson_predictions,
                fold.dixon_coles_predictions,
            )
            for prediction in predictions
        )


def _validate_expected_goals(home_rate: float, away_rate: float) -> None:
    if (
        not isfinite(home_rate)
        or not isfinite(away_rate)
        or home_rate <= 0.0
        or away_rate <= 0.0
        or home_rate > MAX_EXPECTED_GOALS
        or away_rate > MAX_EXPECTED_GOALS
    ):
        msg = "expected goals must be positive, finite and within the fixed cap"
        raise ScoreModelError(msg)


def poisson_score_matrix(
    home_rate: float,
    away_rate: float,
    *,
    max_goals: int = MAX_SCORE_GOALS,
) -> npt.NDArray[np.float64]:
    """Return a normalized independent score grid indexed home then away goals."""

    _validate_expected_goals(home_rate, away_rate)
    if not 1 <= max_goals <= 100:
        msg = "maximum score goals must be between 1 and 100"
        raise ScoreModelError(msg)

    def probabilities(rate: float) -> npt.NDArray[np.float64]:
        values = np.empty(max_goals + 1, dtype=np.float64)
        values[0] = exp(-rate)
        for goals in range(1, max_goals + 1):
            values[goals] = values[goals - 1] * rate / goals
        return values

    matrix = np.outer(probabilities(home_rate), probabilities(away_rate))
    mass = float(matrix.sum())
    if not isfinite(mass) or mass <= 0.0:
        msg = "Poisson score grid has invalid probability mass"
        raise ScoreModelError(msg)
    return matrix / mass


def _outcomes_from_score_matrix(
    matrix: npt.NDArray[np.float64],
) -> OutcomeProbabilities:
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        msg = "score probability matrix must be square"
        raise ScoreModelError(msg)
    home_win = round(float(np.tril(matrix, k=-1).sum()), 15)
    draw = round(float(np.trace(matrix)), 15)
    return OutcomeProbabilities(
        home_win=home_win,
        draw=draw,
        away_win=1.0 - home_win - draw,
    )


def poisson_outcome_probabilities(
    home_rate: float,
    away_rate: float,
    *,
    max_goals: int = MAX_SCORE_GOALS,
) -> OutcomeProbabilities:
    """Project an independent score distribution to three match outcomes."""

    return _outcomes_from_score_matrix(
        poisson_score_matrix(home_rate, away_rate, max_goals=max_goals)
    )


def _poisson_objective_and_gradient(
    coefficients: npt.NDArray[np.float64],
    home_indices: npt.NDArray[np.int64],
    away_indices: npt.NDArray[np.int64],
    home_goals: npt.NDArray[np.float64],
    away_goals: npt.NDArray[np.float64],
    team_count: int,
    parameters: PoissonModelParameters,
) -> tuple[float, npt.NDArray[np.float64]]:
    intercept = coefficients[0]
    home_advantage = coefficients[1]
    attack = coefficients[2 : 2 + team_count]
    defence = coefficients[2 + team_count :]
    home_eta = intercept + home_advantage + attack[home_indices] + defence[away_indices]
    away_eta = intercept + attack[away_indices] + defence[home_indices]
    lower = log(parameters.minimum_expected_goals)
    upper = log(parameters.maximum_expected_goals)
    clipped_home = np.clip(home_eta, lower, upper)
    clipped_away = np.clip(away_eta, lower, upper)
    home_rates = np.exp(clipped_home)
    away_rates = np.exp(clipped_away)
    home_residuals = (home_rates - home_goals) * (
        (home_eta >= lower) & (home_eta <= upper)
    )
    away_residuals = (away_rates - away_goals) * (
        (away_eta >= lower) & (away_eta <= upper)
    )
    row_count = len(home_goals)
    gradient = np.zeros_like(coefficients)
    gradient[0] = float(np.sum(home_residuals + away_residuals)) / row_count
    gradient[1] = float(np.sum(home_residuals)) / row_count
    np.add.at(gradient[2 : 2 + team_count], home_indices, home_residuals / row_count)
    np.add.at(gradient[2 : 2 + team_count], away_indices, away_residuals / row_count)
    np.add.at(gradient[2 + team_count :], away_indices, home_residuals / row_count)
    np.add.at(gradient[2 + team_count :], home_indices, away_residuals / row_count)
    gradient[1:] += parameters.l2_strength * coefficients[1:]
    negative_log_likelihood = float(
        np.mean(
            home_rates
            - home_goals * clipped_home
            + away_rates
            - away_goals * clipped_away
        )
    )
    penalty = 0.5 * parameters.l2_strength * float(np.sum(coefficients[1:] ** 2))
    return negative_log_likelihood + penalty, gradient


def fit_independent_poisson(
    examples: Sequence[TrainingExample],
    parameters: PoissonModelParameters = DEFAULT_POISSON_PARAMETERS,
) -> FittedIndependentPoisson:
    """Fit deterministic team attack, defence and home-advantage rates."""

    if not examples:
        msg = "Poisson fitting requires training examples"
        raise ScoreModelError(msg)
    if parameters.minimum_expected_goals >= parameters.maximum_expected_goals:
        msg = "Poisson expected-goal bounds are invalid"
        raise ScoreModelError(msg)
    ordered = tuple(sorted(examples, key=lambda item: (item.kickoff_at, item.id)))
    team_ids = tuple(
        sorted(
            {
                team_id
                for example in ordered
                for team_id in (example.home_team_id, example.away_team_id)
            },
            key=str,
        )
    )
    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    home_indices = np.asarray(
        [team_index[example.home_team_id] for example in ordered], dtype=np.int64
    )
    away_indices = np.asarray(
        [team_index[example.away_team_id] for example in ordered], dtype=np.int64
    )
    home_goals = np.asarray(
        [example.target.home_goals for example in ordered], dtype=np.float64
    )
    away_goals = np.asarray(
        [example.target.away_goals for example in ordered], dtype=np.float64
    )
    mean_home = float(np.mean(home_goals))
    mean_away = float(np.mean(away_goals))
    if mean_home <= 0.0 or mean_away <= 0.0:
        msg = "Poisson fitting requires positive mean goals for both teams"
        raise ScoreModelError(msg)
    coefficients = np.zeros(2 + 2 * len(team_ids), dtype=np.float64)
    coefficients[0] = log(mean_away)
    coefficients[1] = log(mean_home / mean_away)
    first_moment = np.zeros_like(coefficients)
    second_moment = np.zeros_like(coefficients)
    objective = float("inf")
    for iteration in range(1, parameters.optimizer_iterations + 1):
        objective, gradient = _poisson_objective_and_gradient(
            coefficients,
            home_indices,
            away_indices,
            home_goals,
            away_goals,
            len(team_ids),
            parameters,
        )
        first_moment = (
            parameters.beta_one * first_moment + (1.0 - parameters.beta_one) * gradient
        )
        second_moment = (
            parameters.beta_two * second_moment
            + (1.0 - parameters.beta_two) * gradient**2
        )
        corrected_first = first_moment / (1.0 - parameters.beta_one**iteration)
        corrected_second = second_moment / (1.0 - parameters.beta_two**iteration)
        coefficients -= (
            parameters.learning_rate
            * corrected_first
            / (np.sqrt(corrected_second) + parameters.epsilon)
        )
    if not isfinite(objective) or not np.isfinite(coefficients).all():
        msg = "Poisson optimization produced non-finite parameters"
        raise ScoreModelError(msg)
    return FittedIndependentPoisson(
        team_ids=team_ids,
        intercept=float(coefficients[0]),
        home_advantage=float(coefficients[1]),
        attack=coefficients[2 : 2 + len(team_ids)].copy(),
        defence=coefficients[2 + len(team_ids) :].copy(),
        parameters=parameters,
        diagnostics=PoissonFitDiagnostics(
            training_row_count=len(ordered),
            team_count=len(team_ids),
            optimizer_iterations=parameters.optimizer_iterations,
            final_objective=objective,
            mean_home_goals=mean_home,
            mean_away_goals=mean_away,
        ),
    )


def dixon_coles_tau(
    home_goals: int,
    away_goals: int,
    home_rate: float,
    away_rate: float,
    rho: float,
) -> float:
    """Return the Dixon-Coles multiplicative correction for one scoreline."""

    _validate_expected_goals(home_rate, away_rate)
    if not DIXON_COLES_RHO_MIN <= rho <= DIXON_COLES_RHO_MAX:
        msg = "Dixon-Coles rho is outside the deterministic safe interval"
        raise ScoreModelError(msg)
    if home_goals < 0 or away_goals < 0:
        msg = "Dixon-Coles scoreline goals cannot be negative"
        raise ScoreModelError(msg)
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_rate * away_rate * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_rate * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_rate * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def fit_dixon_coles_rho(
    model: FittedIndependentPoisson,
    examples: Sequence[TrainingExample],
) -> DixonColesFitDiagnostics:
    """Fit rho on the same chronological training window as its Poisson model."""

    if not examples:
        msg = "Dixon-Coles fitting requires training examples"
        raise ScoreModelError(msg)
    rows = tuple(
        (
            example.target.home_goals,
            example.target.away_goals,
            *model.expected_goals(example),
        )
        for example in examples
    )
    low_score_count = sum(home <= 1 and away <= 1 for home, away, _, _ in rows)

    def objective(rho: float) -> float:
        corrections = tuple(
            dixon_coles_tau(home, away, home_rate, away_rate, rho)
            for home, away, home_rate, away_rate in rows
        )
        return -sum(log(correction) for correction in corrections) / len(rows)

    lower = model.parameters.dixon_coles_rho_minimum
    upper = model.parameters.dixon_coles_rho_maximum
    ratio = (5.0**0.5 - 1.0) / 2.0
    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)
    left_value = objective(left)
    right_value = objective(right)
    for _ in range(model.parameters.dixon_coles_optimizer_iterations):
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
    rho = (lower + upper) / 2.0
    return DixonColesFitDiagnostics(
        training_row_count=len(rows),
        rho=rho,
        low_score_row_count=low_score_count,
        adjustment_negative_log_likelihood=objective(rho),
    )


def dixon_coles_outcome_probabilities(
    home_rate: float,
    away_rate: float,
    rho: float,
    *,
    max_goals: int = MAX_SCORE_GOALS,
) -> OutcomeProbabilities:
    """Project the low-score-adjusted score grid to three outcomes."""

    matrix = poisson_score_matrix(home_rate, away_rate, max_goals=max_goals)
    matrix[0, 0] *= dixon_coles_tau(0, 0, home_rate, away_rate, rho)
    matrix[0, 1] *= dixon_coles_tau(0, 1, home_rate, away_rate, rho)
    matrix[1, 0] *= dixon_coles_tau(1, 0, home_rate, away_rate, rho)
    matrix[1, 1] *= dixon_coles_tau(1, 1, home_rate, away_rate, rho)
    mass = float(matrix.sum())
    if not isfinite(mass) or mass <= 0.0 or np.any(matrix < 0.0):
        msg = "Dixon-Coles adjustment produced invalid probability mass"
        raise ScoreModelError(msg)
    return _outcomes_from_score_matrix(matrix / mass)


def _prediction(
    example: TrainingExample,
    probabilities: OutcomeProbabilities,
    *,
    method: Literal["poisson", "dixon_coles"],
    configuration_id: str,
    partition_id: str,
    source_training_dataset_id: str,
    source_training_sha256: str,
) -> ProbabilisticPrediction:
    return ProbabilisticPrediction(
        id=deterministic_prediction_id(
            source_training_sha256=source_training_sha256,
            source_training_example_id=example.id,
            partition_id=partition_id,
            method=method,
            method_version=SCORE_MODEL_METHOD_VERSION,
            configuration_id=configuration_id,
        ),
        method=method,
        method_version=SCORE_MODEL_METHOD_VERSION,
        configuration_id=configuration_id,
        partition_id=partition_id,
        source_training_dataset_id=source_training_dataset_id,
        source_training_sha256=source_training_sha256,
        source_training_example_id=example.id,
        fixture_id=example.fixture_id,
        season_id=example.season_id,
        kickoff_at=example.kickoff_at,
        feature_cutoff_at=example.feature_cutoff_at,
        probabilities=probabilities,
    )


def evaluate_score_models_walk_forward(
    examples: Sequence[TrainingExample],
    *,
    source_training_dataset_id: str,
    source_training_sha256: str,
    parameters: PoissonModelParameters = DEFAULT_POISSON_PARAMETERS,
) -> ScoreModelEvaluationResult:
    """Evaluate Poisson and Dixon-Coles on the five development folds."""

    available_seasons = tuple(sorted({example.season_id for example in examples}))
    if available_seasons != EXPECTED_INPUT_SEASONS:
        msg = "score evaluation requires the complete verified eleven-season corpus"
        raise ScoreModelError(msg)
    folds: list[ScoreModelFoldResult] = []
    for window in walk_forward_windows():
        reference = examples_for_seasons(examples, window.reference_season_ids)
        evaluation = examples_for_seasons(examples, window.evaluation_season_ids)
        if max(item.kickoff_at for item in reference) >= min(
            item.feature_cutoff_at for item in evaluation
        ):
            msg = "score-model reference rows must precede evaluation rows"
            raise ScoreModelError(msg)
        poisson = fit_independent_poisson(reference, parameters)
        dixon_coles = fit_dixon_coles_rho(poisson, reference)
        poisson_predictions: list[ProbabilisticPrediction] = []
        dixon_coles_predictions: list[ProbabilisticPrediction] = []
        for example in evaluation:
            home_rate, away_rate = poisson.expected_goals(example)
            poisson_predictions.append(
                _prediction(
                    example,
                    poisson_outcome_probabilities(
                        home_rate,
                        away_rate,
                        max_goals=parameters.maximum_score_goals,
                    ),
                    method="poisson",
                    configuration_id=POISSON_CONFIGURATION_ID,
                    partition_id=window.id,
                    source_training_dataset_id=source_training_dataset_id,
                    source_training_sha256=source_training_sha256,
                )
            )
            dixon_coles_predictions.append(
                _prediction(
                    example,
                    dixon_coles_outcome_probabilities(
                        home_rate,
                        away_rate,
                        dixon_coles.rho,
                        max_goals=parameters.maximum_score_goals,
                    ),
                    method="dixon_coles",
                    configuration_id=DIXON_COLES_CONFIGURATION_ID,
                    partition_id=window.id,
                    source_training_dataset_id=source_training_dataset_id,
                    source_training_sha256=source_training_sha256,
                )
            )
        actual = {example.id: example.target.outcome for example in evaluation}
        folds.append(
            ScoreModelFoldResult(
                partition_id=window.id,
                reference_season_ids=window.reference_season_ids,
                evaluation_season_id=window.evaluation_season_ids[0],
                poisson_fit=poisson.diagnostics,
                dixon_coles_fit=dixon_coles,
                poisson_predictions=tuple(poisson_predictions),
                dixon_coles_predictions=tuple(dixon_coles_predictions),
                poisson_metric=evaluate_probabilistic_predictions(
                    poisson_predictions,
                    actual,
                ),
                dixon_coles_metric=evaluate_probabilistic_predictions(
                    dixon_coles_predictions,
                    actual,
                ),
            )
        )

    evaluation_examples = examples_for_seasons(
        examples,
        tuple(window.evaluation_season_ids[0] for window in walk_forward_windows()),
    )
    actual = {example.id: example.target.outcome for example in evaluation_examples}
    aggregate_poisson_predictions = tuple(
        prediction for fold in folds for prediction in fold.poisson_predictions
    )
    aggregate_dixon_coles_predictions = tuple(
        prediction for fold in folds for prediction in fold.dixon_coles_predictions
    )
    development = examples_for_seasons(examples, DEVELOPMENT_SEASONS)
    final_poisson = fit_independent_poisson(development, parameters)
    final_dixon_coles = fit_dixon_coles_rho(final_poisson, development)
    return ScoreModelEvaluationResult(
        parameters=parameters,
        folds=tuple(folds),
        aggregate_poisson_metric=evaluate_probabilistic_predictions(
            aggregate_poisson_predictions,
            actual,
        ),
        aggregate_dixon_coles_metric=evaluate_probabilistic_predictions(
            aggregate_dixon_coles_predictions,
            actual,
        ),
        final_poisson_fit=final_poisson.diagnostics,
        final_dixon_coles_fit=final_dixon_coles,
    )
