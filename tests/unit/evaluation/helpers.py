"""Small deterministic training examples for model-evaluation tests."""

from datetime import UTC, datetime
from uuid import UUID

from pl_platform.domain.features import PredictorSet, PredictorValue, TrainingLabel
from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome
from pl_platform.domain.training import (
    TrainingExample,
    deterministic_training_example_id,
)

PREDICTOR_NAMES = (
    "away_elo_expected_score",
    "feature_signal",
    "home_elo_expected_score",
)
SOURCE_DATASET_ID = "test-training-dataset"
SOURCE_TRAINING_SHA256 = "a" * 64


def make_example(
    index: int,
    season_id: str,
    outcome: MatchOutcome,
    *,
    signal: float | None = 0.0,
    home_elo: float = 0.6,
) -> TrainingExample:
    feature_row_id = UUID(int=10_000 + index)
    kickoff = datetime(int(season_id[:4]), 8, 1, 12 + index % 6, tzinfo=UTC)
    if outcome == MatchOutcome.HOME_WIN:
        home_goals, away_goals = 2, 0
    elif outcome == MatchOutcome.DRAW:
        home_goals, away_goals = 1, 1
    else:
        home_goals, away_goals = 0, 2
    predictors = PredictorSet(
        schema_id="epl-pre-match",
        schema_version=2,
        values=(
            PredictorValue(
                name="away_elo_expected_score",
                value=1.0 - home_elo,
            ),
            PredictorValue(name="feature_signal", value=signal),
            PredictorValue(name="home_elo_expected_score", value=home_elo),
        ),
    )
    return TrainingExample(
        id=deterministic_training_example_id(feature_row_id, SOURCE_DATASET_ID),
        feature_row_id=feature_row_id,
        fixture_id=UUID(int=20_000 + index),
        competition_id="eng-premier-league",
        season_id=season_id,
        home_team_id=UUID(int=1),
        away_team_id=UUID(int=2),
        kickoff_at=kickoff,
        kickoff_precision=KickoffPrecision.EXACT,
        feature_cutoff_at=kickoff,
        predictors=predictors,
        target=TrainingLabel(
            outcome=outcome,
            home_goals=home_goals,
            away_goals=away_goals,
        ),
        source_feature_dataset_id=SOURCE_DATASET_ID,
    )


def complete_corpus() -> tuple[TrainingExample, ...]:
    seasons = tuple(f"{year:04d}-{year + 1:04d}" for year in range(2015, 2026))
    rows: list[TrainingExample] = []
    index = 1
    for season in seasons:
        for outcome, signal, elo in (
            (MatchOutcome.HOME_WIN, 2.0, 0.7),
            (MatchOutcome.DRAW, 0.0, 0.5),
            (MatchOutcome.AWAY_WIN, -2.0, 0.3),
        ):
            rows.append(
                make_example(index, season, outcome, signal=signal, home_elo=elo)
            )
            index += 1
    return tuple(rows)
