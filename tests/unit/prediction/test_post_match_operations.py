"""Steps 7.5 through 7.7 append-only post-match lifecycle coverage."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.domain.fixtures import FixtureScore, FixtureStatus
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.domain.simulation import SimulationFixture
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.prediction import (
    ApprovedSimulationFixture,
    CompletedPredictionEvaluation,
    CompletedResultEvidence,
    CurrentFixtureEvidence,
    CurrentModelPrediction,
    PredictionLifecycleError,
    TeamStateAdvancement,
    advance_team_state,
    approve_explicit_scoreline_distribution,
    build_upcoming_feature_rows,
    evaluate_completed_prediction,
    generate_current_predictions,
    regenerate_future_predictions,
    regenerate_season_simulation,
)
from pl_platform.prediction.domain import current_prediction_identity
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.prediction.test_lifecycle import _active_model
from tests.unit.simulation.helpers import distribution


def _evaluation_for_result(
    result: CompletedResultEvidence,
) -> CompletedPredictionEvaluation:
    fixture = result.fixture
    prediction_id, checksum, _ = current_prediction_identity(
        feature_id=UUID(int=7001),
        feature_identity_sha256="7" * 64,
        registry_entry_id=UUID(int=7002),
        registry_head_event_id=UUID(int=7003),
        registry_head_event_sha256="8" * 64,
        model_id=UUID(int=7004),
        artifact_id=UUID(int=7005),
        manifest_id=UUID(int=7006),
        artifact_manifest_sha256="9" * 64,
        configuration_id="catboost-depth6-regularized",
    )
    prediction = CurrentModelPrediction(
        id=prediction_id,
        identity_sha256=checksum,
        feature_id=UUID(int=7001),
        feature_identity_sha256="7" * 64,
        fixture_id=fixture.id,
        competition_id="eng-premier-league",
        season_id=fixture.season_id,
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
        kickoff_at=fixture.kickoff_at,
        feature_cutoff_at=datetime(2026, 8, 14, tzinfo=UTC),
        registry_entry_id=UUID(int=7002),
        registry_head_event_id=UUID(int=7003),
        registry_head_event_sha256="8" * 64,
        model_id=UUID(int=7004),
        artifact_id=UUID(int=7005),
        manifest_id=UUID(int=7006),
        artifact_manifest_sha256="9" * 64,
        configuration_id="catboost-depth6-regularized",
        probabilities=OutcomeProbabilities(home_win=0.6, draw=0.25, away_win=0.15),
    )
    return evaluate_completed_prediction(prediction, result)


def _advancement() -> tuple[
    TeamStateAdvancement,
    CurrentFixtureEvidence,
    PremierLeagueSeason,
    dict[UUID, SeasonOpeningPrior],
    dict[UUID, float],
]:
    upcoming, completed, season, priors, ratings = feature_inputs()
    advancement = advance_team_state(
        season=season,
        initial_elo_ratings=ratings,
        evaluations=(_evaluation_for_result(completed),),
        results=(completed,),
    )
    return advancement, upcoming, season, priors, ratings


def test_result_batch_advances_elo_and_team_state_exactly_once() -> None:
    advancement, _, season, _, ratings = _advancement()

    assert advancement.pre_state.completed_results == ()
    assert len(advancement.post_state.completed_results) == 1
    assert (
        advancement.pre_state.identity_sha256 != advancement.post_state.identity_sha256
    )
    assert (
        advance_team_state(
            season=season,
            initial_elo_ratings=ratings,
            evaluations=tuple(item.evaluation for item in advancement.applied_results),
            results=tuple(item.result for item in advancement.applied_results),
        )
        == advancement
    )

    with pytest.raises(PredictionLifecycleError) as repeated:
        advance_team_state(
            season=season,
            initial_elo_ratings=ratings,
            evaluations=tuple(item.evaluation for item in advancement.applied_results),
            results=tuple(item.result for item in advancement.applied_results),
            previous_advancement=advancement,
        )
    assert repeated.value.code == "result_already_applied"


def test_state_chain_continues_by_batch_and_rejects_gaps() -> None:
    advancement, upcoming, season, _, ratings = _advancement()
    score = FixtureScore(home=1, away=1)
    next_result = CompletedResultEvidence(
        fixture=upcoming.fixture.model_copy(
            update={
                "status": FixtureStatus.FINISHED,
                "full_time_score": score,
                "outcome": score.outcome,
            }
        ),
        result_id=UUID(int=2010),
        result_identity_sha256="d" * 64,
        observation_id=UUID(int=3010),
        cache_key_sha256="e" * 64,
        retrieved_at=datetime(2026, 9, 20, 17, tzinfo=UTC),
    )
    continued = advance_team_state(
        season=season,
        initial_elo_ratings=ratings,
        evaluations=(_evaluation_for_result(next_result),),
        results=(next_result,),
        previous_advancement=advancement,
    )
    assert continued.prior_advancement_id == advancement.id
    assert len(continued.post_state.completed_results) == 2

    with pytest.raises(PredictionLifecycleError) as multiple_batches:
        advance_team_state(
            season=season,
            initial_elo_ratings=ratings,
            evaluations=(
                advancement.applied_results[0].evaluation,
                _evaluation_for_result(next_result),
            ),
            results=(advancement.applied_results[0].result, next_result),
        )
    assert multiple_batches.value.code == "chronology_violation"

    with pytest.raises(PredictionLifecycleError) as mismatch:
        advance_team_state(
            season=season,
            initial_elo_ratings=ratings,
            evaluations=(_evaluation_for_result(next_result),),
            results=(advancement.applied_results[0].result,),
        )
    assert mismatch.value.code == "state_chain_invalid"


def test_advanced_state_regenerates_only_stale_future_prediction(
    tmp_path: Path,
) -> None:
    advancement, upcoming, season, priors, ratings = _advancement()
    prior_feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    active = _active_model(tmp_path)
    prior_prediction = generate_current_predictions((prior_feature,), active)[0]
    refreshed = upcoming.model_copy(
        update={
            "revision_id": UUID(int=4010),
            "revision_identity_sha256": "a" * 64,
            "observation_id": UUID(int=5010),
            "cache_key_sha256": "b" * 64,
            "batch_id": UUID(int=6010),
            "batch_identity_sha256": "c" * 64,
            "retrieved_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
            "knowledge_available_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
        }
    )

    regenerated = regenerate_future_predictions(
        advancement=advancement,
        prior_features=(prior_feature,),
        prior_predictions=(prior_prediction,),
        refreshed_fixtures=(refreshed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
        active_model=active,
    )[0]

    assert regenerated.prior_prediction == prior_prediction
    assert regenerated.replacement_prediction.id != prior_prediction.id
    assert regenerated.replacement_feature.completed_results == (
        advancement.applied_results[0].result,
    )
    assert regenerated.replacement_prediction.probabilities != OutcomeProbabilities(
        home_win=0.0, draw=0.0, away_win=1.0
    )

    with pytest.raises(PredictionLifecycleError) as current:
        regenerate_future_predictions(
            advancement=advancement,
            prior_features=(regenerated.replacement_feature,),
            prior_predictions=(regenerated.replacement_prediction,),
            refreshed_fixtures=(refreshed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
            active_model=active,
        )
    assert current.value.code == "regeneration_not_required"


def test_advanced_state_regenerates_deterministic_simulation_from_explicit_scores() -> (
    None
):
    advancement, upcoming, _, _, _ = _advancement()
    fixture = upcoming.fixture
    scorelines = distribution(fixture.id, fixture.home_team_id, fixture.away_team_id)
    approved = approve_explicit_scoreline_distribution(
        SimulationFixture(
            fixture_id=fixture.id,
            season_id=fixture.season_id,
            kickoff_at=fixture.kickoff_at,
            kickoff_precision=fixture.kickoff_precision,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            scoreline_distribution=scorelines,
        ),
        producer_identity="synthetic-reviewed-scorelines",
        producer_version="1",
        runtime_contract="python-3.14.7",
        numerical_contract="float64-mass-1e-12",
        approval_context="unit-test-only",
    )

    first = regenerate_season_simulation(
        advancement=advancement,
        previous_simulation_id=UUID(int=9001),
        approved_fixtures=(approved,),
        simulation_seed=20260915,
    )
    second = regenerate_season_simulation(
        advancement=advancement,
        previous_simulation_id=UUID(int=9001),
        approved_fixtures=(approved,),
        simulation_seed=20260915,
    )

    assert first.regeneration == second.regeneration
    assert first.summary == second.summary
    assert first.result.points.shape == (10_000, 20)
    assert approved.provenance.producer_kind == "explicit_input"
    assert not hasattr(approved.provenance, "prediction_probabilities")
    assert (
        sha256_bytes(canonical_json_bytes(first.simulation_input))
        == first.regeneration.replacement_input_sha256
    )

    with pytest.raises(PredictionLifecycleError) as unchanged:
        regenerate_season_simulation(
            advancement=advancement,
            previous_simulation_id=first.result.simulation_id,
            approved_fixtures=(approved,),
            simulation_seed=20260915,
        )
    assert unchanged.value.code == "regeneration_not_required"

    other_fixture = approved.fixture.model_copy(
        update={
            "fixture_id": UUID(int=1099),
            "scoreline_distribution": distribution(
                UUID(int=1099), fixture.home_team_id, fixture.away_team_id
            ),
        }
    )
    with pytest.raises(PredictionLifecycleError) as wrong_approval:
        ApprovedSimulationFixture(
            fixture=other_fixture,
            provenance=approved.provenance,
        )
    assert wrong_approval.value.code == "scoreline_provenance_required"
