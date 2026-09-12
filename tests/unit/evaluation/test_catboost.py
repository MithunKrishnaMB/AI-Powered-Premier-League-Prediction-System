"""Tests for deterministic CatBoost fitting and temporal tuning."""

import numpy as np
import pytest
from pydantic import ValidationError

from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.evaluation.catboost_model import (
    CatBoostFitDiagnostics,
    CatBoostModelError,
    CatBoostParameters,
    FittedCatBoostClassifier,
    fit_catboost_classifier,
)
from pl_platform.evaluation.catboost_tuning import (
    CatBoostTuningError,
    tune_catboost_with_walk_forward,
)
from tests.unit.evaluation.helpers import (
    PREDICTOR_NAMES,
    SOURCE_TRAINING_SHA256,
    complete_corpus,
    make_example,
)


def _candidate(identifier: str, *, depth: int = 2) -> CatBoostParameters:
    return CatBoostParameters(
        id=identifier,
        iterations=5,
        depth=depth,
        learning_rate=0.1,
        l2_leaf_reg=3.0,
    )


def test_catboost_fit_is_three_way_deterministic_and_handles_missing_values() -> None:
    training = tuple(
        make_example(
            index,
            "2022-2023",
            outcome,
            signal=None if index == 1 else signal,
            home_elo=elo,
        )
        for index, (outcome, signal, elo) in enumerate(
            (
                (MatchOutcome.HOME_WIN, 2.0, 0.7),
                (MatchOutcome.DRAW, 0.0, 0.5),
                (MatchOutcome.AWAY_WIN, -2.0, 0.3),
                (MatchOutcome.HOME_WIN, 1.0, 0.65),
                (MatchOutcome.DRAW, 0.0, 0.5),
                (MatchOutcome.AWAY_WIN, -1.0, 0.35),
            ),
            start=1,
        )
    )
    parameters = _candidate("catboost-test")
    first = fit_catboost_classifier(training, PREDICTOR_NAMES, parameters)
    second = fit_catboost_classifier(
        tuple(reversed(training)),
        PREDICTOR_NAMES,
        parameters,
    )
    first_probabilities = first.predict_probabilities(training[0].predictors)
    second_probabilities = second.predict_probabilities(training[0].predictors)

    assert first_probabilities == second_probabilities
    assert first_probabilities.home_win + first_probabilities.draw + (
        first_probabilities.away_win
    ) == pytest.approx(1.0)
    assert first.diagnostics.tree_count == 5
    assert np.array_equal(first.model.classes_, np.asarray((0, 1, 2)))
    assert sum(first.normalized_feature_importances()) == pytest.approx(1.0)


def test_catboost_rejects_invalid_structural_importances() -> None:
    class InvalidImportanceModel:
        def get_feature_importance(self, *, type: str) -> object:
            assert type == "PredictionValuesChange"
            return (0.0, -1.0, 1.0)

    fitted = FittedCatBoostClassifier(
        predictor_names=PREDICTOR_NAMES,
        model=InvalidImportanceModel(),  # type: ignore[arg-type]
        diagnostics=CatBoostFitDiagnostics(
            candidate_id="catboost-test",
            tree_count=1,
            predictor_count=3,
            training_row_count=3,
        ),
    )

    with pytest.raises(CatBoostModelError, match="structural feature importances"):
        fitted.normalized_feature_importances()


def test_catboost_contracts_fail_closed() -> None:
    with pytest.raises(ValidationError):
        CatBoostParameters(
            id="invalid",
            iterations=0,
            depth=0,
            learning_rate=0.0,
            l2_leaf_reg=0.0,
        )
    with pytest.raises(CatBoostModelError, match="training examples"):
        fit_catboost_classifier((), PREDICTOR_NAMES, _candidate("catboost-test"))
    one_class = tuple(
        make_example(index, "2022-2023", MatchOutcome.HOME_WIN)
        for index in range(20, 23)
    )
    with pytest.raises(CatBoostModelError, match="every outcome"):
        fit_catboost_classifier(
            one_class,
            PREDICTOR_NAMES,
            _candidate("catboost-test"),
        )


def test_catboost_tuning_uses_only_expanding_development_folds() -> None:
    candidates = (
        _candidate("catboost-small-a", depth=2),
        _candidate("catboost-small-b", depth=3),
    )
    result = tune_catboost_with_walk_forward(
        tuple(reversed(complete_corpus())),
        PREDICTOR_NAMES,
        source_training_dataset_id="test-training-dataset",
        source_training_sha256=SOURCE_TRAINING_SHA256,
        candidates=candidates,
    )

    assert len(result.candidates) == 2
    assert result.selected_candidate_id in {candidate.id for candidate in candidates}
    assert len(result.selected_predictions) == 15
    assert result.final_development_fit.training_row_count == 30
    assert all(
        prediction.season_id != "2025-2026"
        for prediction in result.selected_predictions
    )
    assert all(
        prediction.configuration_id == result.selected_candidate_id
        for prediction in result.selected_predictions
    )


def test_catboost_tuning_rejects_empty_and_duplicate_candidate_sets() -> None:
    with pytest.raises(CatBoostTuningError, match="at least one"):
        tune_catboost_with_walk_forward(
            complete_corpus(),
            PREDICTOR_NAMES,
            source_training_dataset_id="test-training-dataset",
            source_training_sha256=SOURCE_TRAINING_SHA256,
            candidates=(),
        )
    duplicate = _candidate("catboost-duplicate")
    with pytest.raises(CatBoostTuningError, match="unique"):
        tune_catboost_with_walk_forward(
            complete_corpus(),
            PREDICTOR_NAMES,
            source_training_dataset_id="test-training-dataset",
            source_training_sha256=SOURCE_TRAINING_SHA256,
            candidates=(duplicate, duplicate),
        )
