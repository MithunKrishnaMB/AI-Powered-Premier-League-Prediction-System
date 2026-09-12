"""Tests for explicit holdout and expanding walk-forward evaluation."""

import pytest

from pl_platform.domain.features import TrainingLabel
from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.evaluation.logistic import LogisticRegressionParameters
from pl_platform.evaluation.walk_forward import (
    EXCLUDED_SEASONS,
    HOLDOUT_WINDOW,
    WalkForwardError,
    evaluate_holdout_and_walk_forward,
    evaluate_partition,
    walk_forward_windows,
)
from tests.unit.evaluation.helpers import (
    PREDICTOR_NAMES,
    SOURCE_TRAINING_SHA256,
    complete_corpus,
)

FAST_PARAMETERS = LogisticRegressionParameters(
    maximum_iterations=100,
    convergence_tolerance=1e-3,
    convergence_patience=2,
)


def test_walk_forward_uses_expanding_complete_season_folds() -> None:
    windows = walk_forward_windows()

    assert len(windows) == 5
    assert windows[0].reference_season_ids == (
        "2015-2016",
        "2016-2017",
        "2017-2018",
        "2018-2019",
        "2019-2020",
    )
    assert windows[0].evaluation_season_ids == ("2020-2021",)
    assert windows[-1].reference_season_ids[-1] == "2023-2024"
    assert windows[-1].evaluation_season_ids == ("2024-2025",)
    assert EXCLUDED_SEASONS == ("2025-2026",)


def test_complete_evaluation_excludes_last_season_and_is_deterministic() -> None:
    corpus = complete_corpus()
    result = evaluate_holdout_and_walk_forward(
        tuple(reversed(corpus)),
        PREDICTOR_NAMES,
        source_training_dataset_id="test-training",
        source_training_sha256=SOURCE_TRAINING_SHA256,
        logistic_parameters=FAST_PARAMETERS,
    )

    assert result.holdout.reference_row_count == 24
    assert result.holdout.evaluation_row_count == 6
    assert len(result.walk_forward_folds) == 5
    assert len(result.predictions) == 63
    assert all(prediction.season_id != "2025-2026" for prediction in result.predictions)
    assert all(
        metric.prediction_count == 15
        for metric in result.walk_forward_aggregate_metrics
    )


def test_evaluation_targets_cannot_change_predictions() -> None:
    corpus = complete_corpus()
    original = evaluate_partition(
        corpus,
        PREDICTOR_NAMES,
        HOLDOUT_WINDOW,
        source_training_dataset_id="test-training",
        source_training_sha256=SOURCE_TRAINING_SHA256,
        logistic_parameters=FAST_PARAMETERS,
    )
    changed = list(corpus)
    evaluation_index = next(
        index
        for index, example in enumerate(changed)
        if example.season_id == "2023-2024"
    )
    changed[evaluation_index] = changed[evaluation_index].model_copy(
        update={
            "target": TrainingLabel(
                outcome=MatchOutcome.AWAY_WIN,
                home_goals=0,
                away_goals=1,
            )
        }
    )
    perturbed = evaluate_partition(
        changed,
        PREDICTOR_NAMES,
        HOLDOUT_WINDOW,
        source_training_dataset_id="test-training",
        source_training_sha256=SOURCE_TRAINING_SHA256,
        logistic_parameters=FAST_PARAMETERS,
    )

    assert original.predictions == perturbed.predictions
    assert original.metrics != perturbed.metrics


def test_complete_evaluation_requires_the_exact_historical_window() -> None:
    corpus = tuple(
        example for example in complete_corpus() if example.season_id != "2025-2026"
    )
    try:
        evaluate_holdout_and_walk_forward(
            corpus,
            PREDICTOR_NAMES,
            source_training_dataset_id="test-training",
            source_training_sha256=SOURCE_TRAINING_SHA256,
            logistic_parameters=FAST_PARAMETERS,
        )
    except WalkForwardError as exc:
        assert "complete 2015-2016" in str(exc)
    else:  # pragma: no cover - assertion documents fail-closed behavior.
        raise AssertionError("incomplete corpus was accepted")


def test_partition_rejects_a_nonconverged_logistic_fit() -> None:
    with pytest.raises(WalkForwardError, match="did not converge"):
        evaluate_partition(
            complete_corpus(),
            PREDICTOR_NAMES,
            HOLDOUT_WINDOW,
            source_training_dataset_id="test-training",
            source_training_sha256=SOURCE_TRAINING_SHA256,
            logistic_parameters=LogisticRegressionParameters(maximum_iterations=1),
        )
