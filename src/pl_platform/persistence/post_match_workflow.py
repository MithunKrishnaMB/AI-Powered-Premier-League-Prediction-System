"""PostgreSQL journal for deterministic post-match workflow recovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.persistence.prediction import PredictionLifecycleRepository
from pl_platform.persistence.prediction_operations import PredictionOperationsRepository
from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    ImmutableRow,
    PersistenceTable,
    PostgresAggregateRepository,
    StoredObject,
)
from pl_platform.prediction.workflow import (
    POST_MATCH_WORKFLOW_STAGES,
    PostMatchWorkflow,
    PostMatchWorkflowError,
    PostMatchWorkflowEvent,
    PostMatchWorkflowFailureCode,
    PostMatchWorkflowHistory,
    PostMatchWorkflowPayload,
    PostMatchWorkflowStage,
    next_post_match_workflow_event,
    post_match_workflow_event_identity,
    post_match_workflow_identity,
)
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes


def _canonical_object(payload: bytes, format_id: str) -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
    )


def _workflow_row(workflow: PostMatchWorkflow, object_sha256: str) -> ImmutableRow:
    return ImmutableRow.build(
        PersistenceTable.POST_MATCH_WORKFLOW,
        {
            "workflow_id": workflow.id,
            "identity_sha256": workflow.identity_sha256,
            "workflow_object_sha256": object_sha256,
            "schema_version": workflow.schema_version,
            "season_id": workflow.season_id,
            "evaluation_count": len(workflow.evaluations),
            "evaluation_set_sha256": sha256_bytes(
                canonical_json_bytes(
                    {
                        "references": [
                            item.model_dump(mode="json")
                            for item in workflow.evaluations
                        ]
                    }
                )
            ),
            "advancement_id": workflow.advancement.id,
            "advancement_identity_sha256": workflow.advancement.identity_sha256,
            "prediction_regeneration_count": len(workflow.prediction_regenerations),
            "prediction_regeneration_set_sha256": sha256_bytes(
                canonical_json_bytes(
                    {
                        "references": [
                            item.model_dump(mode="json")
                            for item in workflow.prediction_regenerations
                        ]
                    }
                )
            ),
            "simulation_regeneration_id": workflow.simulation_regeneration.id,
            "simulation_regeneration_identity_sha256": (
                workflow.simulation_regeneration.identity_sha256
            ),
        },
        identity_columns=("workflow_id",),
    )


def _event_row(event: PostMatchWorkflowEvent, object_sha256: str) -> ImmutableRow:
    return ImmutableRow.build(
        PersistenceTable.POST_MATCH_WORKFLOW_EVENT,
        {
            "event_id": event.id,
            "identity_sha256": event.identity_sha256,
            "event_object_sha256": object_sha256,
            "schema_version": event.schema_version,
            "workflow_id": event.workflow_id,
            "workflow_identity_sha256": event.workflow_identity_sha256,
            "sequence": event.sequence,
            "stage": event.stage.value,
            "previous_event_id": event.previous_event_id,
            "previous_event_sha256": event.previous_event_sha256,
            "stage_lineage_sha256": event.stage_lineage_sha256,
        },
        identity_columns=("event_id",),
    )


def post_match_workflow_write_plan(
    workflow: PostMatchWorkflow,
) -> AggregateWritePlan:
    """Create the manifest and planned event atomically."""

    expected_id, expected_checksum, identity_bytes = post_match_workflow_identity(
        season_id=workflow.season_id,
        evaluations=workflow.evaluations,
        advancement=workflow.advancement,
        prediction_regenerations=workflow.prediction_regenerations,
        simulation_regeneration=workflow.simulation_regeneration,
    )
    if expected_id != workflow.id or expected_checksum != workflow.identity_sha256:
        raise PostMatchWorkflowError(
            PostMatchWorkflowFailureCode.PAYLOAD_MISMATCH,
            "workflow identity changed before persistence",
        )
    planned = next_post_match_workflow_event(workflow, None)
    _, _, event_identity_bytes = post_match_workflow_event_identity(
        workflow_id=planned.workflow_id,
        workflow_identity_sha256=planned.workflow_identity_sha256,
        sequence=planned.sequence,
        stage=planned.stage,
        previous_event_id=planned.previous_event_id,
        previous_event_sha256=planned.previous_event_sha256,
        stage_lineage_sha256=planned.stage_lineage_sha256,
    )
    workflow_object = _canonical_object(
        canonical_json_bytes(workflow), "post-match-workflow-v1"
    )
    event_object = _canonical_object(
        canonical_json_bytes(planned), "post-match-workflow-event-v1"
    )
    objects = (
        _canonical_object(identity_bytes, "post-match-workflow-identity-v1"),
        workflow_object,
        _canonical_object(
            event_identity_bytes, "post-match-workflow-event-identity-v1"
        ),
        event_object,
    )
    unique_objects = {item.sha256: item for item in objects}
    return AggregateWritePlan(
        kind=AggregateKind.POST_MATCH_WORKFLOWS,
        identity=workflow.identity_sha256,
        objects=tuple(unique_objects[key] for key in sorted(unique_objects)),
        rows=(
            _workflow_row(workflow, workflow_object.sha256),
            _event_row(planned, event_object.sha256),
        ),
    )


def post_match_workflow_event_write_plan(
    event: PostMatchWorkflowEvent,
) -> AggregateWritePlan:
    """Append exactly one deterministic checkpoint event."""

    _, checksum, identity_bytes = post_match_workflow_event_identity(
        workflow_id=event.workflow_id,
        workflow_identity_sha256=event.workflow_identity_sha256,
        sequence=event.sequence,
        stage=event.stage,
        previous_event_id=event.previous_event_id,
        previous_event_sha256=event.previous_event_sha256,
        stage_lineage_sha256=event.stage_lineage_sha256,
    )
    if checksum != event.identity_sha256:
        raise PostMatchWorkflowError(
            PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
            "workflow event identity changed before persistence",
        )
    event_object = _canonical_object(
        canonical_json_bytes(event), "post-match-workflow-event-v1"
    )
    objects = (
        _canonical_object(identity_bytes, "post-match-workflow-event-identity-v1"),
        event_object,
    )
    return AggregateWritePlan(
        kind=AggregateKind.POST_MATCH_WORKFLOWS,
        identity=event.identity_sha256,
        objects=tuple(sorted(objects, key=lambda item: item.sha256)),
        rows=(_event_row(event, event_object.sha256),),
    )


def _row_values(row: ImmutableRow) -> dict[str, object]:
    return {item.name: item.value for item in row.values}


class PostMatchWorkflowRepository:
    """Strict workflow journal backed by immutable PostgreSQL projections."""

    def __init__(self, repository: PostgresAggregateRepository) -> None:
        self._repository = repository

    def load(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory | None:
        stored_workflow = self._repository.get(
            PersistenceTable.POST_MATCH_WORKFLOW, {"workflow_id": workflow.id}
        )
        if stored_workflow is None:
            return None
        plan = post_match_workflow_write_plan(workflow)
        expected_workflow = _row_values(plan.rows[0])
        if any(
            stored_workflow.get(key) != value
            for key, value in expected_workflow.items()
        ):
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.MANIFEST_CONFLICT,
                "persisted workflow differs from the requested manifest",
            )

        events: list[PostMatchWorkflowEvent] = []
        gap_seen = False
        for sequence in range(len(POST_MATCH_WORKFLOW_STAGES)):
            row = self._repository.get(
                PersistenceTable.POST_MATCH_WORKFLOW_EVENT,
                {"workflow_id": workflow.id, "sequence": sequence},
            )
            if row is None:
                gap_seen = True
                continue
            if gap_seen:
                raise PostMatchWorkflowError(
                    PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                    "workflow history contains an event after a gap",
                )
            try:
                event = PostMatchWorkflowEvent(
                    id=cast(UUID, row["event_id"]),
                    identity_sha256=cast(str, row["identity_sha256"]),
                    workflow_id=cast(UUID, row["workflow_id"]),
                    workflow_identity_sha256=cast(str, row["workflow_identity_sha256"]),
                    sequence=cast(int, row["sequence"]),
                    stage=PostMatchWorkflowStage(cast(str, row["stage"])),
                    previous_event_id=cast(UUID | None, row["previous_event_id"]),
                    previous_event_sha256=cast(
                        str | None, row["previous_event_sha256"]
                    ),
                    stage_lineage_sha256=cast(str, row["stage_lineage_sha256"]),
                )
            except (KeyError, ValueError) as exc:
                raise PostMatchWorkflowError(
                    PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                    "persisted workflow event is malformed",
                ) from exc
            events.append(event)
        try:
            return PostMatchWorkflowHistory(workflow=workflow, events=tuple(events))
        except ValidationError as exc:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "persisted workflow events are not a canonical prefix",
            ) from exc

    def create(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory:
        self._repository.persist(post_match_workflow_write_plan(workflow))
        history = self.load(workflow)
        if history is None:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "workflow was not readable after creation",
            )
        return history

    def append(
        self, workflow: PostMatchWorkflow, event: PostMatchWorkflowEvent
    ) -> PostMatchWorkflowHistory:
        existing = self.load(workflow)
        if existing is None:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "workflow event cannot precede its manifest",
            )
        expected = next_post_match_workflow_event(workflow, existing.events[-1])
        if event != expected:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "workflow event is not the next canonical checkpoint",
            )
        self._repository.persist(post_match_workflow_event_write_plan(event))
        history = self.load(workflow)
        if history is None:
            raise PostMatchWorkflowError(
                PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
                "workflow disappeared after event append",
            )
        return history


@dataclass(frozen=True, slots=True)
class RepositoryWorkflowStageExecutor:
    """Production child-write adapter using exact-byte aggregate repositories."""

    lifecycle_repository: PredictionLifecycleRepository
    operations_repository: PredictionOperationsRepository
    opening_priors: Mapping[UUID, SeasonOpeningPrior]
    initial_elo_ratings: Mapping[UUID, float]

    def persist_evaluations(self, payload: PostMatchWorkflowPayload) -> None:
        self.lifecycle_repository.store_completed_evaluations(payload.evaluations)

    def persist_state_advancement(self, payload: PostMatchWorkflowPayload) -> None:
        self.operations_repository.store_advancement(
            payload.advancement,
            initial_elo_ratings=self.initial_elo_ratings,
        )

    def persist_prediction_regenerations(
        self, payload: PostMatchWorkflowPayload
    ) -> None:
        if payload.prediction_regenerations:
            self.operations_repository.store_prediction_regenerations(
                payload.prediction_regenerations,
                opening_priors=self.opening_priors,
                initial_elo_ratings=self.initial_elo_ratings,
            )

    def persist_simulation_regeneration(
        self, payload: PostMatchWorkflowPayload
    ) -> None:
        self.operations_repository.store_simulation_regeneration(payload.simulation)
