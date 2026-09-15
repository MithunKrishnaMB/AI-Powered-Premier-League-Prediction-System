"""Persistence plans for state and regeneration lifecycle records."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock
from uuid import UUID

from pl_platform.domain.simulation import SimulationFixture
from pl_platform.persistence.post_match_workflow import (
    RepositoryWorkflowStageExecutor,
    post_match_workflow_event_write_plan,
    post_match_workflow_write_plan,
)
from pl_platform.persistence.prediction import PredictionLifecycleRepository
from pl_platform.persistence.prediction_operations import (
    PredictionOperationsRepository,
    prediction_regeneration_write_plan,
    simulation_regeneration_write_plan,
    team_state_advancement_write_plan,
)
from pl_platform.persistence.repositories import PersistenceTable
from pl_platform.prediction import (
    approve_explicit_scoreline_distribution,
    build_upcoming_feature_rows,
    compose_post_match_workflow,
    generate_current_predictions,
    next_post_match_workflow_event,
    regenerate_future_predictions,
    regenerate_season_simulation,
)
from tests.unit.prediction.test_lifecycle import _active_model
from tests.unit.prediction.test_post_match_operations import _advancement
from tests.unit.simulation.helpers import distribution


def test_state_and_prediction_regeneration_plans_are_complete(tmp_path: Path) -> None:
    advancement, upcoming, season, priors, ratings = _advancement()
    state_plan = team_state_advancement_write_plan(
        advancement, initial_elo_ratings=ratings
    )
    assert state_plan.rows[-1].table is PersistenceTable.TEAM_STATE_ADVANCEMENT_RESULT

    old_feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    active = _active_model(tmp_path)
    old_prediction = generate_current_predictions((old_feature,), active)[0]
    refreshed = upcoming.model_copy(
        update={
            "revision_id": UUID(int=4110),
            "revision_identity_sha256": "a" * 64,
            "observation_id": UUID(int=5110),
            "cache_key_sha256": "b" * 64,
            "batch_id": UUID(int=6110),
            "batch_identity_sha256": "c" * 64,
            "retrieved_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
            "knowledge_available_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
        }
    )
    regenerations = regenerate_future_predictions(
        advancement=advancement,
        prior_features=(old_feature,),
        prior_predictions=(old_prediction,),
        refreshed_fixtures=(refreshed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
        active_model=active,
    )
    prediction_plan = prediction_regeneration_write_plan(
        regenerations,
        opening_priors=priors,
        initial_elo_ratings=ratings,
    )
    assert prediction_plan.rows[-1].table is PersistenceTable.PREDICTION_REGENERATION


def test_simulation_regeneration_plan_preserves_all_six_exact_arrays() -> None:
    advancement, upcoming, _, _, _ = _advancement()
    fixture = upcoming.fixture
    approved = approve_explicit_scoreline_distribution(
        SimulationFixture(
            fixture_id=fixture.id,
            season_id=fixture.season_id,
            kickoff_at=fixture.kickoff_at,
            kickoff_precision=fixture.kickoff_precision,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            scoreline_distribution=distribution(
                fixture.id, fixture.home_team_id, fixture.away_team_id
            ),
        ),
        producer_identity="synthetic-reviewed-scorelines",
        producer_version="1",
        runtime_contract="python-3.14.7",
        numerical_contract="float64-mass-1e-12",
        approval_context="unit-test-only",
    )
    bundle = regenerate_season_simulation(
        advancement=advancement,
        previous_simulation_id=UUID(int=9002),
        approved_fixtures=(approved,),
        simulation_seed=7,
    )

    plan = simulation_regeneration_write_plan(bundle)

    components = [
        row for row in plan.rows if row.table is PersistenceTable.RESULT_COMPONENT
    ]
    assert len(components) == 6
    assert plan.rows[-1].table is PersistenceTable.SEASON_SIMULATION_REGENERATION


def test_workflow_plans_preserve_manifest_and_hash_linked_event_bytes(
    tmp_path: Path,
) -> None:
    advancement, upcoming, season, priors, ratings = _advancement()
    old_feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    active = _active_model(tmp_path)
    old_prediction = generate_current_predictions((old_feature,), active)[0]
    refreshed = upcoming.model_copy(
        update={
            "revision_id": UUID(int=4310),
            "revision_identity_sha256": "a" * 64,
            "observation_id": UUID(int=5310),
            "cache_key_sha256": "b" * 64,
            "batch_id": UUID(int=6310),
            "batch_identity_sha256": "c" * 64,
            "retrieved_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
            "knowledge_available_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
        }
    )
    regenerations = regenerate_future_predictions(
        advancement=advancement,
        prior_features=(old_feature,),
        prior_predictions=(old_prediction,),
        refreshed_fixtures=(refreshed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
        active_model=active,
    )
    fixture = upcoming.fixture
    approved = approve_explicit_scoreline_distribution(
        SimulationFixture(
            fixture_id=fixture.id,
            season_id=fixture.season_id,
            kickoff_at=fixture.kickoff_at,
            kickoff_precision=fixture.kickoff_precision,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            scoreline_distribution=distribution(
                fixture.id, fixture.home_team_id, fixture.away_team_id
            ),
        ),
        producer_identity="synthetic-reviewed-scorelines",
        producer_version="1",
        runtime_contract="python-3.14.7",
        numerical_contract="float64-mass-1e-12",
        approval_context="unit-test-only",
    )
    simulation = regenerate_season_simulation(
        advancement=advancement,
        previous_simulation_id=UUID(int=9300),
        approved_fixtures=(approved,),
        simulation_seed=7,
    )
    payload = compose_post_match_workflow(
        evaluations=(advancement.applied_results[0].evaluation,),
        advancement=advancement,
        prediction_regenerations=regenerations,
        simulation=simulation,
    )

    create_plan = post_match_workflow_write_plan(payload.workflow)
    planned = next_post_match_workflow_event(payload.workflow, None)
    next_event = next_post_match_workflow_event(payload.workflow, planned)
    append_plan = post_match_workflow_event_write_plan(next_event)

    assert [row.table for row in create_plan.rows] == [
        PersistenceTable.POST_MATCH_WORKFLOW,
        PersistenceTable.POST_MATCH_WORKFLOW_EVENT,
    ]
    assert append_plan.rows[0].table is PersistenceTable.POST_MATCH_WORKFLOW_EVENT
    assert len(create_plan.objects) == 4
    assert len(append_plan.objects) == 2

    lifecycle = Mock()
    operations = Mock()
    executor = RepositoryWorkflowStageExecutor(
        lifecycle_repository=cast(PredictionLifecycleRepository, lifecycle),
        operations_repository=cast(PredictionOperationsRepository, operations),
        opening_priors=priors,
        initial_elo_ratings=ratings,
    )
    executor.persist_evaluations(payload)
    executor.persist_state_advancement(payload)
    executor.persist_prediction_regenerations(payload)
    executor.persist_simulation_regeneration(payload)

    lifecycle.store_completed_evaluations.assert_called_once_with(payload.evaluations)
    operations.store_advancement.assert_called_once_with(
        payload.advancement, initial_elo_ratings=ratings
    )
    operations.store_prediction_regenerations.assert_called_once_with(
        payload.prediction_regenerations,
        opening_priors=priors,
        initial_elo_ratings=ratings,
    )
    operations.store_simulation_regeneration.assert_called_once_with(payload.simulation)
