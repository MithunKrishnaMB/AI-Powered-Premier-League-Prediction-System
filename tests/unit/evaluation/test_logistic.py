"""Tests for deterministic multinomial logistic regression."""

import numpy as np
import pytest

from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.logistic import (
    LogisticRegressionError,
    LogisticRegressionParameters,
    fit_multinomial_logistic_regression,
)
from tests.unit.evaluation.helpers import PREDICTOR_NAMES, make_example


def _training_examples() -> tuple[TrainingExample, ...]:
    rows: list[TrainingExample] = []
    index = 1
    for _ in range(4):
        rows.extend(
            (
                make_example(
                    index,
                    "2022-2023",
                    MatchOutcome.HOME_WIN,
                    signal=2.0,
                ),
                make_example(
                    index + 1,
                    "2022-2023",
                    MatchOutcome.DRAW,
                    signal=0.0,
                    home_elo=0.5,
                ),
                make_example(
                    index + 2,
                    "2022-2023",
                    MatchOutcome.AWAY_WIN,
                    signal=-2.0,
                    home_elo=0.3,
                ),
            )
        )
        index += 3
    return tuple(rows)


def test_logistic_fit_is_deterministic_and_uses_three_way_softmax() -> None:
    rows = _training_examples()
    parameters = LogisticRegressionParameters(
        maximum_iterations=400,
        convergence_tolerance=1e-6,
    )
    first = fit_multinomial_logistic_regression(rows, PREDICTOR_NAMES, parameters)
    second = fit_multinomial_logistic_regression(
        tuple(reversed(rows)),
        PREDICTOR_NAMES,
        parameters,
    )
    home = first.predict_probabilities(
        make_example(
            100,
            "2023-2024",
            MatchOutcome.HOME_WIN,
            signal=3.0,
        ).predictors
    )
    away = first.predict_probabilities(
        make_example(
            101,
            "2023-2024",
            MatchOutcome.AWAY_WIN,
            signal=-3.0,
            home_elo=0.3,
        ).predictors
    )

    assert np.array_equal(first.coefficients, second.coefficients)
    assert np.array_equal(first.intercepts, second.intercepts)
    assert home.home_win > home.away_win
    assert away.away_win > away.home_win
    assert home.home_win + home.draw + home.away_win == pytest.approx(1.0)
    assert first.diagnostics.training_row_count == 12


def test_logistic_preprocessing_is_fitted_only_on_training_rows() -> None:
    rows = list(_training_examples())
    rows[0] = make_example(
        200,
        "2022-2023",
        MatchOutcome.HOME_WIN,
        signal=None,
    )
    model = fit_multinomial_logistic_regression(
        rows,
        PREDICTOR_NAMES,
        LogisticRegressionParameters(maximum_iterations=2),
    )
    prediction = model.predict_probabilities(
        make_example(
            201,
            "2023-2024",
            MatchOutcome.DRAW,
            signal=None,
        ).predictors
    )

    assert model.imputation_means.shape == (3,)
    assert prediction.home_win > 0.0
    assert model.diagnostics.converged is False


def test_logistic_rejects_empty_malformed_or_single_class_training() -> None:
    with pytest.raises(LogisticRegressionError, match="training examples"):
        fit_multinomial_logistic_regression((), PREDICTOR_NAMES)
    with pytest.raises(LogisticRegressionError, match="non-empty"):
        fit_multinomial_logistic_regression(_training_examples(), ())

    one_class = tuple(
        make_example(index, "2022-2023", MatchOutcome.HOME_WIN, signal=1.0)
        for index in range(300, 304)
    )
    with pytest.raises(LogisticRegressionError, match="every outcome"):
        fit_multinomial_logistic_regression(one_class, PREDICTOR_NAMES)

    model = fit_multinomial_logistic_regression(
        _training_examples(),
        PREDICTOR_NAMES,
        LogisticRegressionParameters(maximum_iterations=2),
    )
    wrong_schema = make_example(
        400,
        "2023-2024",
        MatchOutcome.DRAW,
    ).predictors.model_copy(update={"schema_version": 1})
    with pytest.raises(LogisticRegressionError, match="schema"):
        model.predict_probabilities(wrong_schema)
