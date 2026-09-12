"""Tests for independent-Poisson and Dixon-Coles score models."""

from datetime import UTC, datetime
from uuid import UUID

import numpy as np
import pytest

from pl_platform.evaluation.score_models import (
    DixonColesFitDiagnostics,
    PoissonModelParameters,
    ScoreModelError,
    dixon_coles_outcome_probabilities,
    dixon_coles_tau,
    evaluate_score_models_walk_forward,
    fit_dixon_coles_rho,
    fit_independent_poisson,
    poisson_outcome_probabilities,
    poisson_score_matrix,
)
from tests.unit.evaluation.helpers import (
    SOURCE_DATASET_ID,
    SOURCE_TRAINING_SHA256,
    complete_corpus,
)

FAST_PARAMETERS = PoissonModelParameters(
    optimizer_iterations=80,
    dixon_coles_optimizer_iterations=40,
)


def test_poisson_score_grid_and_outcomes_are_normalized() -> None:
    matrix = poisson_score_matrix(1.7, 1.1)
    probabilities = poisson_outcome_probabilities(1.7, 1.1)
    symmetric = poisson_outcome_probabilities(1.2, 1.2)

    assert matrix.shape == (41, 41)
    assert float(matrix.sum()) == pytest.approx(1.0)
    assert probabilities.home_win > probabilities.away_win
    assert symmetric.home_win == pytest.approx(symmetric.away_win)
    with pytest.raises(ScoreModelError, match="positive"):
        poisson_score_matrix(0.0, 1.0)
    with pytest.raises(ScoreModelError, match="between"):
        poisson_score_matrix(1.0, 1.0, max_goals=0)
    with pytest.raises(ScoreModelError, match="fixed cap"):
        poisson_score_matrix(7.0, 1.0)


def test_independent_poisson_fit_is_deterministic_and_handles_unseen_team() -> None:
    training = complete_corpus()[:15]

    first = fit_independent_poisson(training, FAST_PARAMETERS)
    second = fit_independent_poisson(tuple(reversed(training)), FAST_PARAMETERS)
    unseen = training[0].model_copy(update={"home_team_id": UUID(int=999)})

    assert first.intercept == pytest.approx(second.intercept)
    assert np.array_equal(first.attack, second.attack)
    assert first.diagnostics.training_row_count == 15
    assert all(rate > 0.0 for rate in first.expected_goals(unseen))
    assert first.probabilities(unseen).home_win >= 0.0
    with pytest.raises(ScoreModelError, match="requires training"):
        fit_independent_poisson((), FAST_PARAMETERS)
    invalid_bounds = FAST_PARAMETERS.model_copy(
        update={"minimum_expected_goals": 2.0, "maximum_expected_goals": 1.0}
    )
    with pytest.raises(ScoreModelError, match="bounds"):
        fit_independent_poisson(training, invalid_bounds)


def test_dixon_coles_correction_and_fit_are_deterministic() -> None:
    assert dixon_coles_tau(0, 0, 1.5, 1.0, -0.1) == pytest.approx(1.15)
    assert dixon_coles_tau(0, 1, 1.5, 1.0, -0.1) == pytest.approx(0.85)
    assert dixon_coles_tau(1, 0, 1.5, 1.0, -0.1) == pytest.approx(0.9)
    assert dixon_coles_tau(1, 1, 1.5, 1.0, -0.1) == pytest.approx(1.1)
    assert dixon_coles_tau(2, 2, 1.5, 1.0, -0.1) == 1.0
    with pytest.raises(ScoreModelError, match="safe interval"):
        dixon_coles_tau(0, 0, 1.0, 1.0, 0.5)
    with pytest.raises(ScoreModelError, match="negative"):
        dixon_coles_tau(-1, 0, 1.0, 1.0, 0.0)

    training = complete_corpus()[:15]
    model = fit_independent_poisson(training, FAST_PARAMETERS)
    first = fit_dixon_coles_rho(model, training)
    second = fit_dixon_coles_rho(model, tuple(reversed(training)))
    adjusted = dixon_coles_outcome_probabilities(1.5, 1.0, first.rho)

    assert isinstance(first, DixonColesFitDiagnostics)
    assert first.rho == pytest.approx(second.rho)
    assert adjusted.home_win + adjusted.draw + adjusted.away_win == pytest.approx(1.0)
    with pytest.raises(ScoreModelError, match="requires training"):
        fit_dixon_coles_rho(model, ())


def test_score_models_use_only_expanding_development_folds() -> None:
    result = evaluate_score_models_walk_forward(
        complete_corpus(),
        source_training_dataset_id=SOURCE_DATASET_ID,
        source_training_sha256=SOURCE_TRAINING_SHA256,
        parameters=FAST_PARAMETERS,
    )
    repeated = evaluate_score_models_walk_forward(
        tuple(reversed(complete_corpus())),
        source_training_dataset_id=SOURCE_DATASET_ID,
        source_training_sha256=SOURCE_TRAINING_SHA256,
        parameters=FAST_PARAMETERS,
    )

    assert len(result.folds) == 5
    assert len(result.predictions) == 30
    assert result.final_poisson_fit.training_row_count == 30
    assert result.final_dixon_coles_fit.training_row_count == 30
    assert all(prediction.season_id != "2025-2026" for prediction in result.predictions)
    assert result.aggregate_poisson_metric.prediction_count == 15
    assert result.aggregate_dixon_coles_metric.prediction_count == 15
    assert result == repeated


def test_score_model_evaluation_rejects_incomplete_corpus() -> None:
    with pytest.raises(ScoreModelError, match="eleven-season"):
        evaluate_score_models_walk_forward(
            complete_corpus()[:-3],
            source_training_dataset_id=SOURCE_DATASET_ID,
            source_training_sha256=SOURCE_TRAINING_SHA256,
            parameters=FAST_PARAMETERS,
        )
    rows = complete_corpus()
    early_cutoff = rows[15].model_copy(
        update={"feature_cutoff_at": datetime(2010, 1, 1, tzinfo=UTC)}
    )
    with pytest.raises(ScoreModelError, match="precede"):
        evaluate_score_models_walk_forward(
            (*rows[:15], early_cutoff, *rows[16:]),
            source_training_dataset_id=SOURCE_DATASET_ID,
            source_training_sha256=SOURCE_TRAINING_SHA256,
            parameters=FAST_PARAMETERS,
        )


def test_score_model_parameter_contract_rejects_unsafe_bounds() -> None:
    with pytest.raises(ValueError, match="expected-goal bounds"):
        PoissonModelParameters(
            minimum_expected_goals=2.0,
            maximum_expected_goals=1.0,
        )
    with pytest.raises(ValueError, match="rho bounds must"):
        PoissonModelParameters(
            dixon_coles_rho_minimum=0.0,
            dixon_coles_rho_maximum=0.0,
        )
    with pytest.raises(ValueError, match="unsafe"):
        PoissonModelParameters(
            maximum_expected_goals=10.0,
            dixon_coles_rho_maximum=0.025,
        )
