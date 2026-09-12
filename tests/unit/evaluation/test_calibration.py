"""Tests for chronological multiclass temperature calibration."""

import pytest

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.evaluation.calibration import (
    CALIBRATION_EVALUATION_SEASONS,
    CalibrationError,
    TemperatureCalibrationParameters,
    evaluate_expanding_temperature_calibration,
    fit_temperature_scaling,
    temperature_scaled_probabilities,
)
from tests.unit.evaluation.helpers import (
    catboost_predictions,
    complete_corpus,
)


def test_temperature_scaling_is_three_way_and_validates_inputs() -> None:
    probabilities = OutcomeProbabilities(home_win=0.8, draw=0.1, away_win=0.1)

    softened = temperature_scaled_probabilities(probabilities, 2.0)

    assert softened.home_win < probabilities.home_win
    assert softened.home_win + softened.draw + softened.away_win == pytest.approx(1.0)
    with pytest.raises(CalibrationError, match="temperature"):
        temperature_scaled_probabilities(probabilities, 0.0)
    with pytest.raises(CalibrationError, match="floor"):
        temperature_scaled_probabilities(probabilities, 1.0, probability_floor=0.5)
    with pytest.raises(ValueError, match="bounds"):
        TemperatureCalibrationParameters(
            minimum_temperature=2.0,
            maximum_temperature=1.0,
        )


def test_temperature_fit_is_deterministic_and_strict() -> None:
    predictions = catboost_predictions()[:3]
    examples = {example.id: example for example in complete_corpus()}
    outcomes = {
        prediction.source_training_example_id: examples[
            prediction.source_training_example_id
        ].target.outcome
        for prediction in predictions
    }

    first = fit_temperature_scaling(predictions, outcomes)
    second = fit_temperature_scaling(tuple(reversed(predictions)), outcomes)

    assert first.temperature == pytest.approx(second.temperature)
    assert first.training_prediction_count == 3
    with pytest.raises(CalibrationError, match="unique"):
        fit_temperature_scaling(predictions + predictions[:1], outcomes)
    with pytest.raises(CalibrationError, match="populations"):
        fit_temperature_scaling(predictions, {})


def test_expanding_calibration_never_uses_test_season() -> None:
    predictions = catboost_predictions()

    result = evaluate_expanding_temperature_calibration(
        predictions,
        complete_corpus(),
    )
    repeated = evaluate_expanding_temperature_calibration(
        tuple(reversed(predictions)),
        tuple(reversed(complete_corpus())),
    )

    assert tuple(fold.evaluation_season_id for fold in result.folds) == (
        CALIBRATION_EVALUATION_SEASONS
    )
    assert tuple(fold.fit.training_prediction_count for fold in result.folds) == (
        3,
        6,
        9,
        12,
    )
    assert len(result.predictions) == 12
    assert result.final_fit.training_prediction_count == 15
    assert result == repeated
    assert all(
        prediction.method == "catboost_calibrated" for prediction in result.predictions
    )
    assert all(prediction.season_id != "2025-2026" for prediction in result.predictions)


def test_expanding_calibration_rejects_wrong_sources_and_missing_folds() -> None:
    predictions = catboost_predictions()
    wrong_method = predictions[0].model_copy(update={"method": "poisson"})
    wrong_configuration = predictions[0].model_copy(
        update={"configuration_id": "other"}
    )
    test_example = complete_corpus()[-1]
    test_prediction = predictions[0].model_copy(
        update={"season_id": test_example.season_id}
    )

    with pytest.raises(CalibrationError, match="requires source"):
        evaluate_expanding_temperature_calibration((), complete_corpus())
    with pytest.raises(CalibrationError, match="CatBoost"):
        evaluate_expanding_temperature_calibration(
            (wrong_method, *predictions[1:]), complete_corpus()
        )
    with pytest.raises(CalibrationError, match="configuration"):
        evaluate_expanding_temperature_calibration(
            (wrong_configuration, *predictions[1:]), complete_corpus()
        )
    with pytest.raises(CalibrationError, match="untouched"):
        evaluate_expanding_temperature_calibration(
            (test_prediction, *predictions[1:]), complete_corpus()
        )
    with pytest.raises(CalibrationError, match="population"):
        evaluate_expanding_temperature_calibration(predictions[3:], complete_corpus())
    wrong_fold = predictions[0].model_copy(
        update={"partition_id": predictions[3].partition_id}
    )
    with pytest.raises(CalibrationError, match="walk-forward fold"):
        evaluate_expanding_temperature_calibration(
            (wrong_fold, *predictions[1:]), complete_corpus()
        )
