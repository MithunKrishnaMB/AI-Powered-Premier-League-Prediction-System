"""Step 7.2 upcoming-feature contracts."""

from datetime import UTC, datetime

import pytest

from pl_platform.prediction import (
    PredictionLifecycleError,
    UpcomingFeatureRow,
    build_upcoming_feature_rows,
)
from tests.unit.prediction.helpers import feature_inputs


def _build() -> tuple[UpcomingFeatureRow, ...]:
    upcoming, completed, season, priors, ratings = feature_inputs()
    return build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(completed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )


def test_upcoming_features_are_unlabelled_deterministic_and_schema_exact() -> None:
    first = _build()
    second = _build()

    assert first == second
    row = first[0]
    assert row.schema_version == 1
    assert row.predictors.schema_id == "epl-pre-match"
    assert row.predictors.schema_version == 2
    assert len(row.predictors.values) == 175
    assert row.completed_results[0].fixture.outcome == "home_win"
    values = {item.name: item.value for item in row.predictors.values}
    assert values["season_prior_fixtures"] == 1
    assert values["home_prior_matches"] == 1
    assert row.feature_cutoff_at == row.fixture_evidence.knowledge_available_at


def test_results_after_the_knowledge_boundary_are_not_used() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    late = completed.model_copy(
        update={"retrieved_at": datetime(2026, 9, 16, tzinfo=UTC)}
    )

    row = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(late,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]

    assert row.completed_results == ()
    values = {item.name: item.value for item in row.predictors.values}
    assert values["season_prior_fixtures"] == 0
    assert values["home_prior_matches"] == 0


def test_feature_generation_rejects_sealed_and_noncanonical_evidence() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    sealed = season.model_copy(update={"id": "2025-2026"})
    with pytest.raises(PredictionLifecycleError) as error:
        build_upcoming_feature_rows(
            fixtures=(upcoming,),
            completed_results=(completed,),
            season=sealed,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert error.value.code == "sealed_target_prohibited"

    with pytest.raises(PredictionLifecycleError) as duplicate:
        build_upcoming_feature_rows(
            fixtures=(upcoming, upcoming),
            completed_results=(completed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert duplicate.value.code == "invalid_feature_input"


def test_known_result_in_same_or_later_batch_fails_closed() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    future_result = completed.model_copy(
        update={
            "fixture": completed.fixture.model_copy(
                update={"kickoff_at": upcoming.fixture.kickoff_at}
            )
        }
    )
    with pytest.raises(PredictionLifecycleError) as error:
        build_upcoming_feature_rows(
            fixtures=(upcoming,),
            completed_results=(future_result,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert error.value.code == "chronology_violation"
