"""Deterministic metrics for three-way probabilistic predictions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from math import fsum, log
from uuid import UUID

from pl_platform.domain.evaluation import (
    OUTCOME_ORDER,
    OutcomeCounts,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
)
from pl_platform.domain.fixtures import MatchOutcome


class MetricError(ValueError):
    """Predictions and targets do not form one valid evaluation population."""


def evaluate_probabilistic_predictions(
    predictions: Sequence[ProbabilisticPrediction],
    actual_outcomes: Mapping[UUID, MatchOutcome],
) -> ProbabilisticMetricSummary:
    """Score one method over exactly one set of training-example identities."""

    if not predictions:
        msg = "probabilistic evaluation requires predictions"
        raise MetricError(msg)
    methods = {prediction.method for prediction in predictions}
    if len(methods) != 1:
        msg = "one metric summary cannot mix prediction methods"
        raise MetricError(msg)
    identities = tuple(
        prediction.source_training_example_id for prediction in predictions
    )
    if len(identities) != len(set(identities)):
        msg = "evaluation predictions must reference unique training examples"
        raise MetricError(msg)
    if set(identities) != set(actual_outcomes):
        msg = "prediction and target populations must match exactly"
        raise MetricError(msg)

    ordered = sorted(predictions, key=lambda item: item.source_training_example_id)
    log_losses: list[float] = []
    brier_scores: list[float] = []
    ranked_scores: list[float] = []
    counts: Counter[MatchOutcome] = Counter()
    for prediction in ordered:
        actual = actual_outcomes[prediction.source_training_example_id]
        counts[actual] += 1
        actual_probability = prediction.probabilities.for_outcome(actual)
        if actual_probability <= 0.0:
            msg = "log loss is undefined for a zero-probability observed outcome"
            raise MetricError(msg)
        log_losses.append(-log(actual_probability))

        probabilities = tuple(
            prediction.probabilities.for_outcome(outcome) for outcome in OUTCOME_ORDER
        )
        observations = tuple(
            1.0 if outcome == actual else 0.0 for outcome in OUTCOME_ORDER
        )
        brier_scores.append(
            fsum(
                (probability - observation) ** 2
                for probability, observation in zip(
                    probabilities,
                    observations,
                    strict=True,
                )
            )
        )
        ranked_scores.append(
            fsum(
                (fsum(probabilities[:boundary]) - fsum(observations[:boundary])) ** 2
                for boundary in (1, 2)
            )
            / 2.0
        )

    count = len(ordered)
    return ProbabilisticMetricSummary(
        method=ordered[0].method,
        prediction_count=count,
        outcome_counts=OutcomeCounts(
            home_win=counts[MatchOutcome.HOME_WIN],
            draw=counts[MatchOutcome.DRAW],
            away_win=counts[MatchOutcome.AWAY_WIN],
        ),
        mean_log_loss=fsum(log_losses) / count,
        mean_multiclass_brier_score=fsum(brier_scores) / count,
        mean_ranked_probability_score=fsum(ranked_scores) / count,
    )
