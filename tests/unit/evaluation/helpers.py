"""Small deterministic training examples for model-evaluation tests."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from pl_platform.domain.features import PredictorSet, PredictorValue, TrainingLabel
from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome
from pl_platform.domain.training import (
    TrainingExample,
    deterministic_training_example_id,
)
from pl_platform.features.materialize import FeaturePredictorSchema
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    TrainingFeatureSource,
    TrainingInputChecksums,
    TrainingTargetSchema,
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


def make_training_manifest() -> TrainingDatasetManifest:
    names_payload = json.dumps(
        PREDICTOR_NAMES,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    seasons = tuple(f"{year:04d}-{year + 1:04d}" for year in range(2015, 2026))
    sources = tuple(
        TrainingFeatureSource(
            dataset_id=f"features-{season}",
            season_id=season,
            feature_row_count=3,
            features_sha256=f"{index:x}".rjust(64, "0"),
            feature_manifest_sha256=f"{index + 20:x}".rjust(64, "0"),
            canonical_dataset_id=f"canonical-{season}",
            canonical_fixtures_sha256=f"{index + 40:x}".rjust(64, "0"),
            historical_context_sha256=f"{index + 60:x}".rjust(64, "0"),
            raw_source_id="verified-source",
            raw_artifact_id=f"epl-{season}",
            raw_sha256=f"{index + 80:x}".rjust(64, "0"),
            raw_captured_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        for index, season in enumerate(seasons, start=1)
    )
    return TrainingDatasetManifest(
        dataset_schema_version=1,
        dataset_id="test-training-dataset",
        competition_id="eng-premier-league",
        season_ids=seasons,
        training_row_count=33,
        training_sha256=SOURCE_TRAINING_SHA256,
        training_row_schema_version=1,
        predictor_schema=FeaturePredictorSchema(
            id="epl-pre-match",
            version=2,
            predictor_count=3,
            predictor_names=PREDICTOR_NAMES,
            predictor_names_sha256=hashlib.sha256(names_payload).hexdigest(),
        ),
        target_schema=TrainingTargetSchema(
            id="full-time-result-and-score",
            version=1,
            fields=("outcome", "home_goals", "away_goals"),
            outcome_values=("home_win", "draw", "away_win"),
        ),
        ordered_by=("kickoff_at", "training_example_id"),
        input_checksums=TrainingInputChecksums(
            historical_manifest_sha256="b" * 64,
            team_registry_sha256="c" * 64,
            season_registry_sha256="d" * 64,
        ),
        source_feature_datasets=sources,
    )


def training_manifest_payload(manifest: TrainingDatasetManifest) -> bytes:
    return (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()
