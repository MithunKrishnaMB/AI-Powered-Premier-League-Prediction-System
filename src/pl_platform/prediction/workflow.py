"""Deterministic, resumable orchestration for the post-match lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.prediction.domain import (
    CompletedPredictionEvaluation,
    PredictionRegeneration,
    TeamStateAdvancement,
)
from pl_platform.prediction.operations import SimulationRegenerationBundle
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes

POST_MATCH_WORKFLOW_SCHEMA_VERSION: Final = 1


class PostMatchWorkflowFailureCode(StrEnum):
    """Stable failure categories exposed by the workflow boundary."""

    PAYLOAD_MISMATCH = "workflow_payload_mismatch"
    MANIFEST_CONFLICT = "workflow_manifest_conflict"
    HISTORY_MALFORMED = "workflow_history_malformed"
    STAGE_INTERRUPTED = "workflow_stage_interrupted"


class PostMatchWorkflowError(ValueError):
    """The requested workflow or its persisted history is invalid."""

    def __init__(self, code: PostMatchWorkflowFailureCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


class PostMatchWorkflowInterrupted(RuntimeError):
    """A retryable child-persistence or journal boundary was interrupted."""

    def __init__(self, stage: PostMatchWorkflowStage) -> None:
        self.code = PostMatchWorkflowFailureCode.STAGE_INTERRUPTED
        self.stage = stage
        super().__init__(f"{self.code.value}: {stage.value}")


class PostMatchWorkflowStage(StrEnum):
    """Canonical append-only workflow event order."""

    PLANNED = "planned"
    EVALUATIONS_PERSISTED = "evaluations_persisted"
    STATE_ADVANCEMENT_PERSISTED = "state_advancement_persisted"
    PREDICTIONS_REGENERATED = "predictions_regenerated"
    SIMULATION_REGENERATED = "simulation_regenerated"
    COMPLETED = "completed"


POST_MATCH_WORKFLOW_STAGES: Final = tuple(PostMatchWorkflowStage)


class WorkflowChildReference(BaseModel):
    """Stable identity of one immutable child aggregate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IdentifiedWorkflowChild(Protocol):
    """Structural identity shared by every workflow child aggregate."""

    id: UUID
    identity_sha256: str


def _reference(value: IdentifiedWorkflowChild) -> WorkflowChildReference:
    return WorkflowChildReference(id=value.id, identity_sha256=value.identity_sha256)


def _reference_set_sha256(values: tuple[WorkflowChildReference, ...]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {"references": [item.model_dump(mode="json") for item in values]}
        )
    )


def post_match_workflow_identity(
    *,
    season_id: str,
    evaluations: tuple[WorkflowChildReference, ...],
    advancement: WorkflowChildReference,
    prediction_regenerations: tuple[WorkflowChildReference, ...],
    simulation_regeneration: WorkflowChildReference,
) -> tuple[UUID, str, bytes]:
    """Return the UUIDv5 identity and canonical bytes for a workflow manifest."""

    payload = canonical_json_bytes(
        {
            "advancement": advancement.model_dump(mode="json"),
            "evaluations": [item.model_dump(mode="json") for item in evaluations],
            "prediction_regenerations": [
                item.model_dump(mode="json") for item in prediction_regenerations
            ],
            "schema_version": POST_MATCH_WORKFLOW_SCHEMA_VERSION,
            "season_id": season_id,
            "simulation_regeneration": simulation_regeneration.model_dump(mode="json"),
        }
    )
    checksum = sha256_bytes(payload)
    return (
        uuid5(
            NAMESPACE_URL,
            "pl-platform:post-match-workflow:"
            f"{POST_MATCH_WORKFLOW_SCHEMA_VERSION}|{checksum}",
        ),
        checksum,
        payload,
    )


class PostMatchWorkflow(BaseModel):
    """Immutable manifest binding all deterministic post-match children."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = POST_MATCH_WORKFLOW_SCHEMA_VERSION
    id: UUID
    identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    evaluations: tuple[WorkflowChildReference, ...]
    advancement: WorkflowChildReference
    prediction_regenerations: tuple[WorkflowChildReference, ...]
    simulation_regeneration: WorkflowChildReference

    @model_validator(mode="after")
    def manifest_is_canonical(self) -> Self:
        if self.schema_version != POST_MATCH_WORKFLOW_SCHEMA_VERSION:
            raise ValueError("unsupported post-match workflow schema")
        if self.season_id == "2025-2026":
            raise ValueError("sealed 2025-2026 targets cannot enter a workflow")
        if not self.evaluations:
            raise ValueError("post-match workflow requires an evaluation")
        for values, label in (
            (self.evaluations, "evaluations"),
            (self.prediction_regenerations, "prediction regenerations"),
        ):
            if values != tuple(sorted(values, key=lambda item: item.id)):
                raise ValueError(f"workflow {label} must be canonical")
            if len({item.id for item in values}) != len(values):
                raise ValueError(f"workflow {label} repeat an identity")
        expected_id, expected_sha256, _ = post_match_workflow_identity(
            season_id=self.season_id,
            evaluations=self.evaluations,
            advancement=self.advancement,
            prediction_regenerations=self.prediction_regenerations,
            simulation_regeneration=self.simulation_regeneration,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("post-match workflow identity does not match its children")
        return self

    def stage_lineage_sha256(self, stage: PostMatchWorkflowStage) -> str:
        """Return the manifest-pinned lineage checksum for one stage."""

        if stage is PostMatchWorkflowStage.EVALUATIONS_PERSISTED:
            return _reference_set_sha256(self.evaluations)
        if stage is PostMatchWorkflowStage.STATE_ADVANCEMENT_PERSISTED:
            return self.advancement.identity_sha256
        if stage is PostMatchWorkflowStage.PREDICTIONS_REGENERATED:
            return _reference_set_sha256(self.prediction_regenerations)
        if stage is PostMatchWorkflowStage.SIMULATION_REGENERATED:
            return self.simulation_regeneration.identity_sha256
        return self.identity_sha256


def post_match_workflow_event_identity(
    *,
    workflow_id: UUID,
    workflow_identity_sha256: str,
    sequence: int,
    stage: PostMatchWorkflowStage,
    previous_event_id: UUID | None,
    previous_event_sha256: str | None,
    stage_lineage_sha256: str,
) -> tuple[UUID, str, bytes]:
    """Return a deterministic identity for one hash-linked journal event."""

    payload = canonical_json_bytes(
        {
            "previous_event_id": None
            if previous_event_id is None
            else str(previous_event_id),
            "previous_event_sha256": previous_event_sha256,
            "schema_version": POST_MATCH_WORKFLOW_SCHEMA_VERSION,
            "sequence": sequence,
            "stage": stage.value,
            "stage_lineage_sha256": stage_lineage_sha256,
            "workflow_id": str(workflow_id),
            "workflow_identity_sha256": workflow_identity_sha256,
        }
    )
    checksum = sha256_bytes(payload)
    return (
        uuid5(
            NAMESPACE_URL,
            "pl-platform:post-match-workflow-event:"
            f"{POST_MATCH_WORKFLOW_SCHEMA_VERSION}|{checksum}",
        ),
        checksum,
        payload,
    )


class PostMatchWorkflowEvent(BaseModel):
    """One immutable, hash-linked workflow checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = POST_MATCH_WORKFLOW_SCHEMA_VERSION
    id: UUID
    identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workflow_id: UUID
    workflow_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence: int = Field(strict=True, ge=0)
    stage: PostMatchWorkflowStage
    previous_event_id: UUID | None
    previous_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stage_lineage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def event_is_canonical(self) -> Self:
        if self.schema_version != POST_MATCH_WORKFLOW_SCHEMA_VERSION:
            raise ValueError("unsupported post-match workflow event schema")
        if self.sequence >= len(POST_MATCH_WORKFLOW_STAGES):
            raise ValueError("post-match workflow event sequence is out of range")
        if self.stage is not POST_MATCH_WORKFLOW_STAGES[self.sequence]:
            raise ValueError("post-match workflow event stage is out of sequence")
        if (self.previous_event_id is None) != (self.previous_event_sha256 is None):
            raise ValueError("workflow predecessor identity is incomplete")
        if self.sequence == 0 and self.previous_event_id is not None:
            raise ValueError("planned event cannot have a predecessor")
        if self.sequence > 0 and self.previous_event_id is None:
            raise ValueError("workflow checkpoint requires its predecessor")
        expected_id, expected_sha256, _ = post_match_workflow_event_identity(
            workflow_id=self.workflow_id,
            workflow_identity_sha256=self.workflow_identity_sha256,
            sequence=self.sequence,
            stage=self.stage,
            previous_event_id=self.previous_event_id,
            previous_event_sha256=self.previous_event_sha256,
            stage_lineage_sha256=self.stage_lineage_sha256,
        )
        if self.id != expected_id or self.identity_sha256 != expected_sha256:
            raise ValueError("post-match workflow event identity does not match")
        return self


def next_post_match_workflow_event(
    workflow: PostMatchWorkflow,
    previous: PostMatchWorkflowEvent | None,
) -> PostMatchWorkflowEvent:
    """Create the next deterministic event without consulting mutable state."""

    sequence = 0 if previous is None else previous.sequence + 1
    if sequence >= len(POST_MATCH_WORKFLOW_STAGES):
        raise PostMatchWorkflowError(
            PostMatchWorkflowFailureCode.HISTORY_MALFORMED,
            "completed workflow cannot be advanced",
        )
    stage = POST_MATCH_WORKFLOW_STAGES[sequence]
    event_id, checksum, _ = post_match_workflow_event_identity(
        workflow_id=workflow.id,
        workflow_identity_sha256=workflow.identity_sha256,
        sequence=sequence,
        stage=stage,
        previous_event_id=None if previous is None else previous.id,
        previous_event_sha256=None if previous is None else previous.identity_sha256,
        stage_lineage_sha256=workflow.stage_lineage_sha256(stage),
    )
    return PostMatchWorkflowEvent(
        id=event_id,
        identity_sha256=checksum,
        workflow_id=workflow.id,
        workflow_identity_sha256=workflow.identity_sha256,
        sequence=sequence,
        stage=stage,
        previous_event_id=None if previous is None else previous.id,
        previous_event_sha256=None if previous is None else previous.identity_sha256,
        stage_lineage_sha256=workflow.stage_lineage_sha256(stage),
    )


class PostMatchWorkflowHistory(BaseModel):
    """Read-only workflow state derived solely from append-only history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow: PostMatchWorkflow
    events: tuple[PostMatchWorkflowEvent, ...]

    @model_validator(mode="after")
    def history_is_a_complete_valid_prefix(self) -> Self:
        if not self.events:
            raise ValueError("workflow history must include its planned event")
        previous: PostMatchWorkflowEvent | None = None
        for actual in self.events:
            expected = next_post_match_workflow_event(self.workflow, previous)
            if actual != expected:
                raise ValueError("workflow history is not the canonical event prefix")
            previous = actual
        return self

    @property
    def current_stage(self) -> PostMatchWorkflowStage:
        return self.events[-1].stage

    @property
    def is_complete(self) -> bool:
        return self.current_stage is PostMatchWorkflowStage.COMPLETED


@dataclass(frozen=True, slots=True)
class PostMatchWorkflowPayload:
    """Typed in-memory children pinned by one persisted workflow manifest."""

    workflow: PostMatchWorkflow
    evaluations: tuple[CompletedPredictionEvaluation, ...]
    advancement: TeamStateAdvancement
    prediction_regenerations: tuple[PredictionRegeneration, ...]
    simulation: SimulationRegenerationBundle

    def __post_init__(self) -> None:
        evaluations = tuple(sorted(self.evaluations, key=lambda item: item.id))
        predictions = tuple(
            sorted(self.prediction_regenerations, key=lambda item: item.id)
        )
        if (
            evaluations != self.evaluations
            or predictions != self.prediction_regenerations
        ):
            self._invalid("workflow children must use canonical identity order")
        if tuple(_reference(item) for item in evaluations) != self.workflow.evaluations:
            self._invalid("evaluation payload differs from the workflow manifest")
        if _reference(self.advancement) != self.workflow.advancement:
            self._invalid("state advancement differs from the workflow manifest")
        if tuple(_reference(item) for item in predictions) != (
            self.workflow.prediction_regenerations
        ):
            self._invalid("prediction payload differs from the workflow manifest")
        if _reference(self.simulation.regeneration) != (
            self.workflow.simulation_regeneration
        ):
            self._invalid("simulation payload differs from the workflow manifest")
        applied_evaluations = tuple(
            sorted(
                (item.evaluation.id for item in self.advancement.applied_results),
                key=str,
            )
        )
        expected_evaluations = tuple(sorted((item.id for item in evaluations), key=str))
        if applied_evaluations != expected_evaluations:
            self._invalid("state advancement does not apply every evaluation")
        if self.advancement.post_state.season_id != self.workflow.season_id:
            self._invalid("state advancement season differs from the workflow")
        if any(item.season_id != self.workflow.season_id for item in evaluations):
            self._invalid("evaluation season differs from the workflow")
        if any(
            item.replacement_prediction.season_id != self.workflow.season_id
            for item in predictions
        ):
            self._invalid("prediction regeneration season differs from the workflow")
        if (
            any(item.advancement_id != self.advancement.id for item in predictions)
            or self.simulation.regeneration.advancement_id != self.advancement.id
        ):
            self._invalid(
                "regenerated output does not reference the workflow advancement"
            )
        if self.simulation.regeneration.season_id != self.workflow.season_id:
            self._invalid("simulation season differs from the workflow")

    @staticmethod
    def _invalid(message: str) -> None:
        raise PostMatchWorkflowError(
            PostMatchWorkflowFailureCode.PAYLOAD_MISMATCH, message
        )


def compose_post_match_workflow(
    *,
    evaluations: tuple[CompletedPredictionEvaluation, ...],
    advancement: TeamStateAdvancement,
    prediction_regenerations: tuple[PredictionRegeneration, ...],
    simulation: SimulationRegenerationBundle,
) -> PostMatchWorkflowPayload:
    """Bind already-validated child operations into one deterministic manifest."""

    ordered_evaluations = tuple(sorted(evaluations, key=lambda item: item.id))
    ordered_predictions = tuple(
        sorted(prediction_regenerations, key=lambda item: item.id)
    )
    evaluation_refs = tuple(_reference(item) for item in ordered_evaluations)
    prediction_refs = tuple(_reference(item) for item in ordered_predictions)
    advancement_ref = _reference(advancement)
    simulation_ref = _reference(simulation.regeneration)
    workflow_id, checksum, _ = post_match_workflow_identity(
        season_id=advancement.post_state.season_id,
        evaluations=evaluation_refs,
        advancement=advancement_ref,
        prediction_regenerations=prediction_refs,
        simulation_regeneration=simulation_ref,
    )
    workflow = PostMatchWorkflow(
        id=workflow_id,
        identity_sha256=checksum,
        season_id=advancement.post_state.season_id,
        evaluations=evaluation_refs,
        advancement=advancement_ref,
        prediction_regenerations=prediction_refs,
        simulation_regeneration=simulation_ref,
    )
    return PostMatchWorkflowPayload(
        workflow=workflow,
        evaluations=ordered_evaluations,
        advancement=advancement,
        prediction_regenerations=ordered_predictions,
        simulation=simulation,
    )


class PostMatchWorkflowJournal(Protocol):
    """Strict append-only persistence port used by the workflow runner."""

    def load(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory | None: ...

    def create(self, workflow: PostMatchWorkflow) -> PostMatchWorkflowHistory: ...

    def append(
        self, workflow: PostMatchWorkflow, event: PostMatchWorkflowEvent
    ) -> PostMatchWorkflowHistory: ...


class PostMatchWorkflowStageExecutor(Protocol):
    """Idempotent child-write port; every method must verify an exact retry."""

    def persist_evaluations(self, payload: PostMatchWorkflowPayload) -> None: ...

    def persist_state_advancement(self, payload: PostMatchWorkflowPayload) -> None: ...

    def persist_prediction_regenerations(
        self, payload: PostMatchWorkflowPayload
    ) -> None: ...

    def persist_simulation_regeneration(
        self, payload: PostMatchWorkflowPayload
    ) -> None: ...


def run_post_match_workflow(
    payload: PostMatchWorkflowPayload,
    *,
    journal: PostMatchWorkflowJournal,
    executor: PostMatchWorkflowStageExecutor,
) -> PostMatchWorkflowHistory:
    """Run or resume all child writes from the verified append-only prefix."""

    try:
        history = journal.load(payload.workflow)
        if history is None:
            history = journal.create(payload.workflow)
    except PostMatchWorkflowError:
        raise
    except Exception as exc:
        raise PostMatchWorkflowInterrupted(PostMatchWorkflowStage.PLANNED) from exc

    actions = {
        PostMatchWorkflowStage.EVALUATIONS_PERSISTED: executor.persist_evaluations,
        PostMatchWorkflowStage.STATE_ADVANCEMENT_PERSISTED: (
            executor.persist_state_advancement
        ),
        PostMatchWorkflowStage.PREDICTIONS_REGENERATED: (
            executor.persist_prediction_regenerations
        ),
        PostMatchWorkflowStage.SIMULATION_REGENERATED: (
            executor.persist_simulation_regeneration
        ),
    }
    while not history.is_complete:
        event = next_post_match_workflow_event(payload.workflow, history.events[-1])
        try:
            action = actions.get(event.stage)
            if action is not None:
                action(payload)
            history = journal.append(payload.workflow, event)
        except PostMatchWorkflowError:
            raise
        except Exception as exc:
            raise PostMatchWorkflowInterrupted(event.stage) from exc
    return history
