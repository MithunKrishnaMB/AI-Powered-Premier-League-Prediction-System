"""Retry, recovery and partial-failure coverage for post-match workflows."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.simulation import SimulationFixture
from pl_platform.prediction import (
    PostMatchWorkflow,
    PostMatchWorkflowError,
    PostMatchWorkflowEvent,
    PostMatchWorkflowFailureCode,
    PostMatchWorkflowHistory,
    PostMatchWorkflowInterrupted,
    PostMatchWorkflowPayload,
    PostMatchWorkflowStage,
    approve_explicit_scoreline_distribution,
    build_upcoming_feature_rows,
    compose_post_match_workflow,
    generate_current_predictions,
    next_post_match_workflow_event,
    regenerate_future_predictions,
    regenerate_season_simulation,
    run_post_match_workflow,
)
from tests.unit.prediction.test_lifecycle import _active_model
from tests.unit.prediction.test_post_match_operations import _advancement
from tests.unit.simulation.helpers import distribution


def _workflow_payload(tmp_path: Path) -> PostMatchWorkflowPayload:
    advancement, upcoming, season, priors, ratings = _advancement()
    evaluation = advancement.applied_results[0].evaluation
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
            "revision_id": UUID(int=4210),
            "revision_identity_sha256": "a" * 64,
            "observation_id": UUID(int=5210),
            "cache_key_sha256": "b" * 64,
            "batch_id": UUID(int=6210),
            "batch_identity_sha256": "c" * 64,
            "retrieved_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
            "knowledge_available_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
        }
    )
    regenerations = regenerate_future_predictions(
        advancement=advancement,
        prior_features=(prior_feature,),
        prior_predictions=(prior_prediction,),
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
        previous_simulation_id=UUID(int=9200),
        approved_fixtures=(approved,),
        simulation_seed=20260915,
    )
    return compose_post_match_workflow(
        evaluations=(evaluation,),
        advancement=advancement,
        prediction_regenerations=regenerations,
        simulation=simulation,
    )


@pytest.fixture(scope="module")
def workflow_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> PostMatchWorkflowPayload:
    return _workflow_payload(tmp_path_factory.mktemp("post-match-workflow"))


@dataclass
class MemoryJournal:
    histories: dict[UUID, PostMatchWorkflowHistory] = field(default_factory=dict)
    fail_after_append: PostMatchWorkflowStage | None = None

    def load(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory | None:
        history = self.histories.get(workflow.id)
        if history is not None and history.workflow != workflow:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.MANIFEST_CONFLICT,
                "conflicting synthetic manifest",
            )
        return history

    def create(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory:
        existing = self.load(workflow)
        if existing is not None:
            return existing
        history = PostMatchWorkflowHistory(
            workflow=workflow,
            events=(next_post_match_workflow_event(workflow, None),),
        )
        self.histories[workflow.id] = history
        return history

    def append(
        self, workflow: PostMatchWorkflow, event: PostMatchWorkflowEvent
    ) -> PostMatchWorkflowHistory:
        history = self.load(workflow)
        assert history is not None
        expected = next_post_match_workflow_event(workflow, history.events[-1])
        if event != expected:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "non-canonical synthetic event",
            )
        updated = PostMatchWorkflowHistory(
            workflow=workflow, events=(*history.events, event)
        )
        self.histories[workflow.id] = updated
        if self.fail_after_append is event.stage:
            self.fail_after_append = None
            raise OSError("synthetic acknowledgement loss")
        return updated


@dataclass
class RecordingExecutor:
    fail_after_write: PostMatchWorkflowStage | None = None
    calls: list[PostMatchWorkflowStage] = field(default_factory=list)
    stored: set[PostMatchWorkflowStage] = field(default_factory=set)

    def _write(self, stage: PostMatchWorkflowStage) -> None:
        self.calls.append(stage)
        self.stored.add(stage)
        if self.fail_after_write is stage:
            self.fail_after_write = None
            raise OSError("synthetic child acknowledgement loss")

    def persist_evaluations(self, payload: PostMatchWorkflowPayload) -> None:
        assert payload.evaluations
        self._write(PostMatchWorkflowStage.EVALUATIONS_PERSISTED)

    def persist_state_advancement(self, payload: PostMatchWorkflowPayload) -> None:
        assert payload.advancement
        self._write(PostMatchWorkflowStage.STATE_ADVANCEMENT_PERSISTED)

    def persist_prediction_regenerations(
        self, payload: PostMatchWorkflowPayload
    ) -> None:
        assert payload.prediction_regenerations
        self._write(PostMatchWorkflowStage.PREDICTIONS_REGENERATED)

    def persist_simulation_regeneration(
        self, payload: PostMatchWorkflowPayload
    ) -> None:
        assert payload.simulation
        self._write(PostMatchWorkflowStage.SIMULATION_REGENERATED)


def test_workflow_identity_and_event_chain_are_deterministic(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    payload = workflow_payload
    again = compose_post_match_workflow(
        evaluations=payload.evaluations,
        advancement=payload.advancement,
        prediction_regenerations=payload.prediction_regenerations,
        simulation=payload.simulation,
    )
    assert again == payload

    events: list[PostMatchWorkflowEvent] = []
    previous = None
    for _ in range(6):
        previous = next_post_match_workflow_event(payload.workflow, previous)
        events.append(previous)
    history = PostMatchWorkflowHistory(workflow=payload.workflow, events=tuple(events))
    assert history.is_complete
    assert history.current_stage is PostMatchWorkflowStage.COMPLETED


@pytest.mark.parametrize(
    "failed_stage",
    (
        PostMatchWorkflowStage.EVALUATIONS_PERSISTED,
        PostMatchWorkflowStage.STATE_ADVANCEMENT_PERSISTED,
        PostMatchWorkflowStage.PREDICTIONS_REGENERATED,
        PostMatchWorkflowStage.SIMULATION_REGENERATED,
    ),
)
def test_retry_recovers_after_child_write_without_double_application(
    workflow_payload: PostMatchWorkflowPayload, failed_stage: PostMatchWorkflowStage
) -> None:
    payload = workflow_payload
    journal = MemoryJournal()
    executor = RecordingExecutor(fail_after_write=failed_stage)

    with pytest.raises(PostMatchWorkflowInterrupted) as interrupted:
        run_post_match_workflow(payload, journal=journal, executor=executor)
    assert interrupted.value.stage is failed_stage
    assert failed_stage in executor.stored

    completed = run_post_match_workflow(payload, journal=journal, executor=executor)

    assert completed.is_complete
    assert executor.stored == {
        PostMatchWorkflowStage.EVALUATIONS_PERSISTED,
        PostMatchWorkflowStage.STATE_ADVANCEMENT_PERSISTED,
        PostMatchWorkflowStage.PREDICTIONS_REGENERATED,
        PostMatchWorkflowStage.SIMULATION_REGENERATED,
    }
    assert executor.calls.count(failed_stage) == 2


@pytest.mark.parametrize("failed_stage", tuple(PostMatchWorkflowStage)[1:])
def test_retry_recovers_when_event_commit_acknowledgement_is_lost(
    workflow_payload: PostMatchWorkflowPayload, failed_stage: PostMatchWorkflowStage
) -> None:
    payload = workflow_payload
    journal = MemoryJournal(fail_after_append=failed_stage)
    executor = RecordingExecutor()

    with pytest.raises(PostMatchWorkflowInterrupted) as interrupted:
        run_post_match_workflow(payload, journal=journal, executor=executor)
    assert interrupted.value.stage is failed_stage

    completed = run_post_match_workflow(payload, journal=journal, executor=executor)
    assert completed.is_complete
    if failed_stage is not PostMatchWorkflowStage.COMPLETED:
        assert executor.calls.count(failed_stage) == 1


def test_completed_retry_is_a_verified_no_op(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    payload = workflow_payload
    journal = MemoryJournal()
    executor = RecordingExecutor()
    first = run_post_match_workflow(payload, journal=journal, executor=executor)
    calls = list(executor.calls)

    second = run_post_match_workflow(payload, journal=journal, executor=executor)

    assert second == first
    assert executor.calls == calls


def test_payload_and_history_corruption_fail_closed(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    payload = workflow_payload
    wrong_simulation = payload.simulation.regeneration.model_copy(
        update={"identity_sha256": "f" * 64}
    )
    with pytest.raises(PostMatchWorkflowError) as mismatch:
        PostMatchWorkflowPayload(
            workflow=payload.workflow,
            evaluations=payload.evaluations,
            advancement=payload.advancement,
            prediction_regenerations=payload.prediction_regenerations,
            simulation=payload.simulation.__class__(
                approved_fixtures=payload.simulation.approved_fixtures,
                simulation_input=payload.simulation.simulation_input,
                result=payload.simulation.result,
                summary=payload.simulation.summary,
                regeneration=wrong_simulation,
            ),
        )
    assert mismatch.value.code is PostMatchWorkflowFailureCode.PAYLOAD_MISMATCH

    planned = next_post_match_workflow_event(payload.workflow, None)
    malformed = planned.model_copy(update={"stage_lineage_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        PostMatchWorkflowHistory(workflow=payload.workflow, events=(malformed,))


def test_manifest_and_event_contracts_reject_every_noncanonical_shape(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    workflow = workflow_payload.workflow
    workflow_data = workflow.model_dump()
    other = workflow.evaluations[0].model_copy(update={"id": UUID(int=1)})
    invalid_manifests = (
        {**workflow_data, "schema_version": 2},
        {**workflow_data, "season_id": "2025-2026"},
        {**workflow_data, "evaluations": ()},
        {**workflow_data, "evaluations": (workflow.evaluations[0], other)},
        {
            **workflow_data,
            "evaluations": (workflow.evaluations[0], workflow.evaluations[0]),
        },
        {
            **workflow_data,
            "prediction_regenerations": (
                workflow.prediction_regenerations[0],
                workflow.prediction_regenerations[0],
            ),
        },
        {**workflow_data, "id": UUID(int=0)},
    )
    for manifest in invalid_manifests:
        with pytest.raises(ValidationError):
            PostMatchWorkflow.model_validate(manifest)

    planned = next_post_match_workflow_event(workflow, None)
    planned_data = planned.model_dump()
    predecessor_id = UUID(int=2)
    invalid_events = (
        {**planned_data, "schema_version": 2},
        {**planned_data, "sequence": 6, "stage": "completed"},
        {
            **planned_data,
            "sequence": 1,
            "stage": "planned",
            "previous_event_id": predecessor_id,
            "previous_event_sha256": "a" * 64,
        },
        {**planned_data, "previous_event_id": predecessor_id},
        {
            **planned_data,
            "previous_event_id": predecessor_id,
            "previous_event_sha256": "a" * 64,
        },
        {
            **planned_data,
            "sequence": 1,
            "stage": "evaluations_persisted",
        },
        {**planned_data, "id": UUID(int=0)},
    )
    for event in invalid_events:
        with pytest.raises(ValidationError):
            PostMatchWorkflowEvent.model_validate(event)

    with pytest.raises(ValidationError):
        PostMatchWorkflowHistory(workflow=workflow, events=())
    completed = planned
    for _ in range(5):
        completed = next_post_match_workflow_event(workflow, completed)
    with pytest.raises(PostMatchWorkflowError) as advanced:
        next_post_match_workflow_event(workflow, completed)
    assert advanced.value.code is PostMatchWorkflowFailureCode.HISTORY_MALFORMED


def test_workflow_start_failures_are_stable(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    executor = RecordingExecutor()

    class BrokenJournal(MemoryJournal):
        def load(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory | None:
            raise OSError("synthetic journal outage")

    with pytest.raises(PostMatchWorkflowInterrupted) as interrupted:
        run_post_match_workflow(
            workflow_payload, journal=BrokenJournal(), executor=executor
        )
    assert interrupted.value.stage is PostMatchWorkflowStage.PLANNED

    conflict = MemoryJournal()
    conflict.histories[workflow_payload.workflow.id] = PostMatchWorkflowHistory(
        workflow=workflow_payload.workflow,
        events=(next_post_match_workflow_event(workflow_payload.workflow, None),),
    )
    conflicting = workflow_payload.workflow.model_copy(
        update={"identity_sha256": "0" * 64}
    )
    with pytest.raises(PostMatchWorkflowError) as manifest_error:
        conflict.load(conflicting)
    assert manifest_error.value.code is PostMatchWorkflowFailureCode.MANIFEST_CONFLICT


def test_payload_cross_child_disagreements_fail_closed(
    workflow_payload: PostMatchWorkflowPayload,
) -> None:
    payload = workflow_payload

    def assert_invalid(**changes: Any) -> None:
        with pytest.raises(PostMatchWorkflowError) as mismatch:
            replace(payload, **changes)
        assert mismatch.value.code is PostMatchWorkflowFailureCode.PAYLOAD_MISMATCH

    wrong_state = payload.advancement.post_state.model_copy(
        update={"season_id": "2027-2028"}
    )
    assert_invalid(evaluations=())
    assert_invalid(
        advancement=payload.advancement.model_copy(update={"identity_sha256": "0" * 64})
    )
    assert_invalid(prediction_regenerations=())
    assert_invalid(
        advancement=payload.advancement.model_copy(update={"applied_results": ()})
    )
    assert_invalid(
        advancement=payload.advancement.model_copy(update={"post_state": wrong_state})
    )
    assert_invalid(
        evaluations=(
            payload.evaluations[0].model_copy(update={"season_id": "2027-2028"}),
        )
    )
    assert_invalid(
        prediction_regenerations=(
            payload.prediction_regenerations[0].model_copy(
                update={
                    "replacement_prediction": payload.prediction_regenerations[
                        0
                    ].replacement_prediction.model_copy(
                        update={"season_id": "2027-2028"}
                    )
                }
            ),
        )
    )
    assert_invalid(
        prediction_regenerations=(
            payload.prediction_regenerations[0].model_copy(
                update={"advancement_id": UUID(int=999)}
            ),
        )
    )
    assert_invalid(
        simulation=payload.simulation.__class__(
            approved_fixtures=payload.simulation.approved_fixtures,
            simulation_input=payload.simulation.simulation_input,
            result=payload.simulation.result,
            summary=payload.simulation.summary,
            regeneration=payload.simulation.regeneration.model_copy(
                update={"season_id": "2027-2028"}
            ),
        )
    )
