"""Tests for benchmark, probability and metric contracts."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.evaluation import (
    ChronologicalEvaluationWindow,
    OutcomeProbabilities,
    ProbabilisticPrediction,
    deterministic_prediction_id,
)
from pl_platform.domain.features import PredictorSet, PredictorValue, TrainingLabel
from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.evaluation.benchmarks import (
    BenchmarkError,
    elo_benchmark_probabilities,
    fit_naive_outcome_prior,
)
from pl_platform.evaluation.metrics import (
    MetricError,
    evaluate_probabilistic_predictions,
)
from tests.unit.evaluation.helpers import (
    SOURCE_TRAINING_SHA256,
    make_example,
)


def _prediction(
    index: int,
    outcome_probabilities: OutcomeProbabilities,
    *,
    method: str = "naive",
) -> ProbabilisticPrediction:
    example = make_example(index, "2024-2025", MatchOutcome.HOME_WIN)
    prediction_id = deterministic_prediction_id(
        source_training_sha256=SOURCE_TRAINING_SHA256,
        source_training_example_id=example.id,
        partition_id="test-partition",
        method=method,  # type: ignore[arg-type]
        method_version=1,
    )
    return ProbabilisticPrediction.model_validate(
        {
            "id": prediction_id,
            "method": method,
            "method_version": 1,
            "partition_id": "test-partition",
            "source_training_dataset_id": "test-training",
            "source_training_sha256": SOURCE_TRAINING_SHA256,
            "source_training_example_id": example.id,
            "fixture_id": example.fixture_id,
            "season_id": example.season_id,
            "kickoff_at": example.kickoff_at,
            "feature_cutoff_at": example.feature_cutoff_at,
            "probabilities": outcome_probabilities,
        }
    )


def test_probability_window_and_prediction_contracts() -> None:
    probabilities = OutcomeProbabilities(home_win=0.5, draw=0.25, away_win=0.25)
    prediction = _prediction(1, probabilities)
    serialized = prediction.model_dump(mode="json")

    assert probabilities.for_outcome(MatchOutcome.HOME_WIN) == 0.5
    assert probabilities.for_outcome(MatchOutcome.DRAW) == 0.25
    assert probabilities.for_outcome(MatchOutcome.AWAY_WIN) == 0.25
    assert "target" not in serialized
    assert prediction.id == deterministic_prediction_id(
        source_training_sha256=SOURCE_TRAINING_SHA256,
        source_training_example_id=prediction.source_training_example_id,
        partition_id="test-partition",
        method="naive",
        method_version=1,
    )

    window = ChronologicalEvaluationWindow(
        id="valid-window",
        reference_season_ids=("2021-2022", "2022-2023"),
        evaluation_season_ids=("2023-2024",),
        excluded_season_ids=("2024-2025",),
    )
    assert window.reference_season_ids[-1] < window.evaluation_season_ids[0]


@pytest.mark.parametrize(
    "payload",
    [
        {"home_win": 0.5, "draw": 0.3, "away_win": 0.3},
        {"home_win": -0.1, "draw": 0.5, "away_win": 0.6},
        {"home_win": True, "draw": 0.5, "away_win": 0.5},
    ],
)
def test_rejects_invalid_probabilities(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OutcomeProbabilities.model_validate(payload)


def test_rejects_overlapping_or_reversed_windows_and_bad_prediction_id() -> None:
    with pytest.raises(ValidationError, match="disjoint"):
        ChronologicalEvaluationWindow(
            id="overlap",
            reference_season_ids=("2022-2023",),
            evaluation_season_ids=("2022-2023",),
        )
    with pytest.raises(ValidationError, match="precede"):
        ChronologicalEvaluationWindow(
            id="reverse",
            reference_season_ids=("2023-2024",),
            evaluation_season_ids=("2022-2023",),
        )
    payload = _prediction(
        2,
        OutcomeProbabilities(home_win=0.5, draw=0.25, away_win=0.25),
    ).model_dump()
    payload["id"] = UUID(int=999)
    with pytest.raises(ValidationError, match="deterministic identity"):
        ProbabilisticPrediction.model_validate(payload)


def test_naive_prior_and_elo_bridge_preserve_three_outcomes() -> None:
    labels = (
        TrainingLabel(outcome=MatchOutcome.HOME_WIN, home_goals=1, away_goals=0),
        TrainingLabel(outcome=MatchOutcome.HOME_WIN, home_goals=2, away_goals=1),
        TrainingLabel(outcome=MatchOutcome.DRAW, home_goals=1, away_goals=1),
        TrainingLabel(outcome=MatchOutcome.AWAY_WIN, home_goals=0, away_goals=1),
    )
    counts, naive = fit_naive_outcome_prior(labels)
    predictors = make_example(
        3,
        "2024-2025",
        MatchOutcome.HOME_WIN,
        home_elo=0.75,
    ).predictors
    elo = elo_benchmark_probabilities(predictors, draw_probability=naive.draw)

    assert counts.total == 4
    assert naive == OutcomeProbabilities(home_win=0.5, draw=0.25, away_win=0.25)
    assert elo.home_win == pytest.approx(0.5625)
    assert elo.draw == 0.25
    assert elo.away_win == pytest.approx(0.1875)


def test_benchmarks_fail_closed_on_incomplete_or_invalid_inputs() -> None:
    home_label = TrainingLabel(
        outcome=MatchOutcome.HOME_WIN,
        home_goals=1,
        away_goals=0,
    )
    with pytest.raises(BenchmarkError, match="reference labels"):
        fit_naive_outcome_prior(())
    with pytest.raises(BenchmarkError, match="every outcome"):
        fit_naive_outcome_prior((home_label,))

    predictors = make_example(4, "2024-2025", MatchOutcome.DRAW).predictors
    missing = PredictorSet(
        schema_id="epl-pre-match",
        schema_version=2,
        values=tuple(
            item for item in predictors.values if item.name != "away_elo_expected_score"
        ),
    )
    non_float = PredictorSet(
        schema_id="epl-pre-match",
        schema_version=2,
        values=tuple(
            PredictorValue(name=item.name, value=None)
            if item.name == "home_elo_expected_score"
            else item
            for item in predictors.values
        ),
    )
    non_complementary = predictors.model_copy(
        update={
            "values": tuple(
                item.model_copy(update={"value": 0.7})
                if item.name == "away_elo_expected_score"
                else item
                for item in predictors.values
            )
        }
    )
    with pytest.raises(BenchmarkError, match="missing predictor"):
        elo_benchmark_probabilities(missing, draw_probability=0.25)
    with pytest.raises(BenchmarkError, match="non-null floats"):
        elo_benchmark_probabilities(non_float, draw_probability=0.25)
    with pytest.raises(BenchmarkError, match="complementary"):
        elo_benchmark_probabilities(non_complementary, draw_probability=0.25)
    with pytest.raises(BenchmarkError, match="between zero and one"):
        elo_benchmark_probabilities(predictors, draw_probability=1.1)


def test_metrics_match_known_multiclass_values_and_reject_bad_populations() -> None:
    perfect = OutcomeProbabilities(home_win=1.0, draw=0.0, away_win=0.0)
    prediction = _prediction(5, perfect)
    actual = {prediction.source_training_example_id: MatchOutcome.HOME_WIN}

    summary = evaluate_probabilistic_predictions((prediction,), actual)

    assert summary.mean_log_loss == 0.0
    assert summary.mean_multiclass_brier_score == 0.0
    assert summary.mean_ranked_probability_score == 0.0
    assert summary.outcome_counts.home_win == 1

    with pytest.raises(MetricError, match="requires predictions"):
        evaluate_probabilistic_predictions((), {})
    with pytest.raises(MetricError, match="populations"):
        evaluate_probabilistic_predictions((prediction,), {})
    with pytest.raises(MetricError, match="zero-probability"):
        evaluate_probabilistic_predictions(
            (prediction,),
            {prediction.source_training_example_id: MatchOutcome.AWAY_WIN},
        )
    elo_prediction = _prediction(6, perfect, method="elo")
    with pytest.raises(MetricError, match="mix"):
        evaluate_probabilistic_predictions(
            (prediction, elo_prediction),
            {
                prediction.source_training_example_id: MatchOutcome.HOME_WIN,
                elo_prediction.source_training_example_id: MatchOutcome.HOME_WIN,
            },
        )
