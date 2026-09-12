"""Deterministic naive and Elo three-way probability benchmarks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from math import isclose
from typing import Final

from pl_platform.domain.evaluation import OutcomeCounts, OutcomeProbabilities
from pl_platform.domain.features import PredictorSet, TrainingLabel
from pl_platform.domain.fixtures import MatchOutcome

BENCHMARK_METHOD_VERSION: Final = 1
ELO_HOME_EXPECTED_SCORE: Final = "home_elo_expected_score"
ELO_AWAY_EXPECTED_SCORE: Final = "away_elo_expected_score"


class BenchmarkError(ValueError):
    """Benchmark inputs cannot produce valid three-way probabilities."""


def fit_naive_outcome_prior(
    labels: Sequence[TrainingLabel],
) -> tuple[OutcomeCounts, OutcomeProbabilities]:
    """Estimate one unconditional three-way distribution from prior labels."""

    if not labels:
        msg = "naive benchmark requires reference labels"
        raise BenchmarkError(msg)
    counts = Counter(label.outcome for label in labels)
    if any(counts[outcome] == 0 for outcome in MatchOutcome):
        msg = "naive benchmark reference window must contain every outcome"
        raise BenchmarkError(msg)
    total = len(labels)
    outcome_counts = OutcomeCounts(
        home_win=counts[MatchOutcome.HOME_WIN],
        draw=counts[MatchOutcome.DRAW],
        away_win=counts[MatchOutcome.AWAY_WIN],
    )
    probabilities = OutcomeProbabilities(
        home_win=outcome_counts.home_win / total,
        draw=outcome_counts.draw / total,
        away_win=outcome_counts.away_win / total,
    )
    return outcome_counts, probabilities


def elo_benchmark_probabilities(
    predictors: PredictorSet,
    *,
    draw_probability: float,
) -> OutcomeProbabilities:
    """Wrap complementary Elo expected scores in a fixed three-way bridge.

    Elo expected score is used only as the relative home/away share of the
    non-draw probability mass. It is not represented as a calibrated match
    outcome probability.
    """

    if predictors.schema_id != "epl-pre-match" or predictors.schema_version != 2:
        msg = "Elo benchmark requires predictor schema epl-pre-match version 2"
        raise BenchmarkError(msg)
    values = {item.name: item.value for item in predictors.values}
    try:
        home_expected = values[ELO_HOME_EXPECTED_SCORE]
        away_expected = values[ELO_AWAY_EXPECTED_SCORE]
    except KeyError as exc:
        msg = f"Elo benchmark is missing predictor {exc.args[0]!r}"
        raise BenchmarkError(msg) from exc
    if type(home_expected) is not float or type(away_expected) is not float:
        msg = "Elo expected-score predictors must be non-null floats"
        raise BenchmarkError(msg)
    if not 0.0 <= draw_probability <= 1.0:
        msg = "Elo draw probability must be between zero and one"
        raise BenchmarkError(msg)
    expected_total = home_expected + away_expected
    if not isclose(expected_total, 1.0, rel_tol=0.0, abs_tol=1e-12):
        msg = "Elo expected-score predictors must be complementary"
        raise BenchmarkError(msg)
    if home_expected < 0.0 or away_expected < 0.0:
        msg = "Elo expected-score predictors cannot be negative"
        raise BenchmarkError(msg)
    home_share = home_expected / expected_total
    home_probability = (1.0 - draw_probability) * home_share
    return OutcomeProbabilities(
        home_win=home_probability,
        draw=draw_probability,
        away_win=1.0 - draw_probability - home_probability,
    )
