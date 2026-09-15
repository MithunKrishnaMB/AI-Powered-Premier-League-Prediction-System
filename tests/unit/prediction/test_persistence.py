"""Immutable write-plan tests for Steps 7.2 through 7.4."""

from datetime import UTC, datetime
from pathlib import Path

from pl_platform.persistence.prediction import (
    completed_evaluations_write_plan,
    predictions_write_plan,
    upcoming_features_write_plan,
)
from pl_platform.persistence.repositories import AggregateKind, PersistenceTable
from pl_platform.prediction import (
    build_upcoming_feature_rows,
    evaluate_completed_prediction,
    generate_current_predictions,
)
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.prediction.test_lifecycle import _active_model


def test_feature_write_plan_preserves_values_state_and_exact_bytes() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(completed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]

    plan = upcoming_features_write_plan(
        (feature,), opening_priors=priors, initial_elo_ratings=ratings
    )

    assert plan.kind is AggregateKind.UPCOMING_FEATURES
    assert sum(row.table is PersistenceTable.UPCOMING_FEATURE for row in plan.rows) == 1
    assert (
        sum(
            row.table is PersistenceTable.UPCOMING_FEATURE_RESULT_SOURCE
            for row in plan.rows
        )
        == 1
    )
    assert (
        sum(row.table is PersistenceTable.UPCOMING_FEATURE_VALUE for row in plan.rows)
        == 175
    )
    assert len(plan.objects) == 6


def test_prediction_and_evaluation_plans_are_separate_and_immutable(
    tmp_path: Path,
) -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(completed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    prediction = generate_current_predictions((feature,), _active_model(tmp_path))[0]
    result = completed.model_copy(
        update={
            "fixture": completed.fixture.model_copy(
                update={
                    "id": prediction.fixture_id,
                    "season_id": prediction.season_id,
                    "home_team_id": prediction.home_team_id,
                    "away_team_id": prediction.away_team_id,
                    "kickoff_at": prediction.kickoff_at,
                }
            ),
            "retrieved_at": datetime(2026, 9, 20, 17, tzinfo=UTC),
        }
    )
    evaluation = evaluate_completed_prediction(prediction, result)

    prediction_plan = predictions_write_plan((prediction,))
    evaluation_plan = completed_evaluations_write_plan((evaluation,))

    assert prediction_plan.kind is AggregateKind.CURRENT_PREDICTIONS
    assert prediction_plan.rows[0].table is PersistenceTable.CURRENT_MODEL_PREDICTION
    assert evaluation_plan.kind is AggregateKind.COMPLETED_PREDICTION_EVALUATIONS
    assert (
        evaluation_plan.rows[0].table
        is PersistenceTable.COMPLETED_PREDICTION_EVALUATION
    )
