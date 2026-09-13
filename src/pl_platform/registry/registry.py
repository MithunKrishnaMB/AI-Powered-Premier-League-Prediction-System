"""Append-only model registry states and fail-closed promotion rules."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ModelArtifactError,
    canonical_json_bytes,
    sha256_bytes,
)
from pl_platform.registry.serialization import load_model_artifact

MODEL_REGISTRY_SCHEMA_VERSION: Final = 1
REGISTRY_NAMESPACE: Final = "pl-platform:model-registry"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
RegistryState = Literal[
    "candidate",
    "development_accepted",
    "active",
    "retired",
    "rejected",
]
RegistryAction = Literal[
    "register",
    "accept_development",
    "activate",
    "retire",
    "reject",
]


class RegistryEntry(BaseModel):
    """Immutable link from a registry identity to one artifact manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    entry_id: UUID
    model_id: UUID
    artifact_id: UUID
    artifact_manifest_id: UUID
    artifact_manifest_relative_path: str = Field(min_length=1)
    artifact_manifest_sha256: Sha256

    @model_validator(mode="after")
    def identity_and_path_must_match(self) -> Self:
        expected = deterministic_registry_entry_id(
            self.artifact_id,
            self.artifact_manifest_sha256,
        )
        if self.entry_id != expected:
            raise ValueError("registry entry ID does not match its artifact")
        path = Path(self.artifact_manifest_relative_path)
        if (
            path.is_absolute()
            or "\\" in self.artifact_manifest_relative_path
            or ".." in path.parts
        ):
            raise ValueError("registry artifact manifest path must be relative")
        return self


class RegistryEvidence(BaseModel):
    """Evidence allowed for a deterministic registry transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_manifest_sha256: Sha256
    assessment_manifest_sha256: Sha256 | None = None
    rejection_reason: str | None = Field(default=None, min_length=1)


class RegistryEvent(BaseModel):
    """One immutable event in a checksum-linked registry history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID
    entry_id: UUID
    sequence: PositiveInt
    previous_event_sha256: Sha256 | None
    action: RegistryAction
    from_state: RegistryState | None
    to_state: RegistryState
    evidence: RegistryEvidence

    @model_validator(mode="after")
    def action_must_match_states_and_evidence(self) -> Self:
        transition = (self.from_state, self.to_state)
        expected_action = {
            (None, "candidate"): "register",
            ("candidate", "development_accepted"): "accept_development",
            ("development_accepted", "active"): "activate",
            ("active", "retired"): "retire",
            ("candidate", "rejected"): "reject",
            ("development_accepted", "rejected"): "reject",
        }.get(transition)
        if self.action != expected_action:
            raise ValueError("registry action is not allowed for the state transition")
        if self.action == "register":
            if self.sequence != 1 or self.previous_event_sha256 is not None:
                raise ValueError("registration must be the first registry event")
        elif self.previous_event_sha256 is None:
            raise ValueError("registry transitions must link the previous event")
        if self.action == "accept_development":
            if self.evidence.assessment_manifest_sha256 is None:
                raise ValueError("development acceptance requires assessment evidence")
        elif self.evidence.assessment_manifest_sha256 is not None:
            raise ValueError(
                "assessment evidence is only valid for development acceptance"
            )
        if self.action == "reject":
            if self.evidence.rejection_reason is None:
                raise ValueError("rejection requires a reason")
        elif self.evidence.rejection_reason is not None:
            raise ValueError("a rejection reason is only valid for rejection")
        if self.action == "activate":
            raise ValueError(
                "active promotion requires a future typed final-test evidence contract"
            )
        expected_id = deterministic_registry_event_id(
            self.entry_id,
            sequence=self.sequence,
            previous_event_sha256=self.previous_event_sha256,
            action=self.action,
            from_state=self.from_state,
            to_state=self.to_state,
            evidence=self.evidence,
        )
        if self.event_id != expected_id:
            raise ValueError("registry event ID does not match its transition")
        return self


@dataclass(frozen=True, slots=True)
class LoadedRegistryEntry:
    entry: RegistryEntry
    events: tuple[RegistryEvent, ...]
    state: RegistryState


@dataclass(frozen=True, slots=True)
class RegistryMutationResult:
    entry_path: Path
    entry_id: str
    artifact_id: str
    state: RegistryState
    event_count: int
    status: Literal["written", "already_current"]


def deterministic_registry_entry_id(
    artifact_id: UUID,
    artifact_manifest_sha256: str,
) -> UUID:
    identity = f"1|{artifact_id}|{artifact_manifest_sha256}"
    return uuid5(NAMESPACE_URL, f"{REGISTRY_NAMESPACE}:entry:{identity}")


def deterministic_registry_event_id(
    entry_id: UUID,
    *,
    sequence: int,
    previous_event_sha256: str | None,
    action: RegistryAction,
    from_state: RegistryState | None,
    to_state: RegistryState,
    evidence: RegistryEvidence,
) -> UUID:
    payload = canonical_json_bytes(
        {
            "action": action,
            "entry_id": str(entry_id),
            "evidence": evidence.model_dump(mode="json"),
            "from_state": from_state,
            "previous_event_sha256": previous_event_sha256,
            "schema_version": MODEL_REGISTRY_SCHEMA_VERSION,
            "sequence": sequence,
            "to_state": to_state,
        }
    )
    return uuid5(
        NAMESPACE_URL,
        f"{REGISTRY_NAMESPACE}:event:{sha256_bytes(payload)}",
    )


def _atomic_write_new(path: Path, payload: bytes) -> bool:
    """Create immutable bytes or accept an exactly identical existing file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return False
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            f"registry path already contains different bytes: {path.name}",
        )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        temporary_path = None
        return True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _event(
    entry: RegistryEntry,
    events: tuple[RegistryEvent, ...],
    *,
    action: RegistryAction,
    to_state: RegistryState,
    evidence: RegistryEvidence,
) -> RegistryEvent:
    from_state: RegistryState | None = events[-1].to_state if events else None
    previous_sha = sha256_bytes(canonical_json_bytes(events[-1])) if events else None
    sequence = len(events) + 1
    event_id = deterministic_registry_event_id(
        entry.entry_id,
        sequence=sequence,
        previous_event_sha256=previous_sha,
        action=action,
        from_state=from_state,
        to_state=to_state,
        evidence=evidence,
    )
    try:
        return RegistryEvent(
            event_id=event_id,
            entry_id=entry.entry_id,
            sequence=sequence,
            previous_event_sha256=previous_sha,
            action=action,
            from_state=from_state,
            to_state=to_state,
            evidence=evidence,
        )
    except ValidationError as exc:
        code = (
            ArtifactFailureCode.FINAL_TEST_EVIDENCE_REQUIRED
            if action == "activate"
            else ArtifactFailureCode.REGISTRY_TRANSITION_INVALID
        )
        raise ModelArtifactError(code, "registry transition was rejected") from exc


def _entry_directory(registry_root: Path, entry_id: UUID) -> Path:
    return registry_root / "v1" / "entries" / str(entry_id)


def _event_path(entry_directory: Path, event: RegistryEvent) -> Path:
    return entry_directory / "events" / f"{event.sequence:06d}-{event.event_id}.json"


def load_registry_entry(entry_path: Path) -> LoadedRegistryEntry:
    """Validate an immutable entry and its complete checksum-linked event chain."""

    try:
        entry_payload = entry_path.read_bytes()
        entry = RegistryEntry.model_validate_json(entry_payload)
    except (OSError, ValidationError) as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_INVALID,
            "registry entry is missing or invalid",
        ) from exc
    if canonical_json_bytes(entry) != entry_payload:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_NON_CANONICAL,
            "registry entry bytes are not canonical",
        )
    event_directory = entry_path.parent / "events"
    expected_entry_children = {entry_path.resolve(), event_directory.resolve()}
    actual_entry_children = {child.resolve() for child in entry_path.parent.iterdir()}
    if actual_entry_children != expected_entry_children:
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            "registry entry directory contains an unexpected path",
        )
    if not event_directory.is_dir():
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            "registry entry has no event directory",
        )
    unexpected = tuple(
        path
        for path in event_directory.iterdir()
        if not path.is_file() or path.suffix != ".json"
    )
    if unexpected:
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            "registry event directory contains an unexpected entry",
        )
    event_paths = tuple(sorted(event_directory.glob("*.json")))
    if not event_paths:
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            "registry entry has no registration event",
        )
    events: list[RegistryEvent] = []
    previous_sha: str | None = None
    state: RegistryState | None = None
    for sequence, path in enumerate(event_paths, start=1):
        payload = path.read_bytes()
        try:
            event = RegistryEvent.model_validate_json(payload)
        except ValidationError as exc:
            raise ModelArtifactError(
                ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
                "registry event contract validation failed",
            ) from exc
        if (
            canonical_json_bytes(event) != payload
            or event.sequence != sequence
            or event.entry_id != entry.entry_id
            or event.previous_event_sha256 != previous_sha
            or event.from_state != state
            or event.evidence.artifact_manifest_sha256 != entry.artifact_manifest_sha256
            or path != _event_path(entry_path.parent, event)
        ):
            raise ModelArtifactError(
                ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
                "registry event ordering or checksum chain is invalid",
            )
        events.append(event)
        previous_sha = sha256_bytes(payload)
        state = event.to_state
    if state is None:  # pragma: no cover - guarded by the non-empty check above.
        raise ModelArtifactError(
            ArtifactFailureCode.REGISTRY_TRANSITION_INVALID,
            "registry state cannot be derived",
        )
    return LoadedRegistryEntry(entry=entry, events=tuple(events), state=state)


def register_model_artifact(
    artifact_manifest_path: Path,
    artifact_root: Path,
    registry_root: Path,
) -> RegistryMutationResult:
    """Register one fully verified artifact as a development candidate."""

    loaded_artifact = load_model_artifact(artifact_manifest_path, artifact_root)
    manifest = loaded_artifact.manifest
    manifest_sha = sha256_bytes(artifact_manifest_path.read_bytes())
    entry_id = deterministic_registry_entry_id(manifest.artifact_id, manifest_sha)
    try:
        relative_path = artifact_manifest_path.resolve().relative_to(
            artifact_root.resolve()
        )
    except ValueError as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.PATH_INVALID,
            "artifact manifest is outside the artifact root",
        ) from exc
    entry = RegistryEntry(
        entry_id=entry_id,
        model_id=manifest.model_id,
        artifact_id=manifest.artifact_id,
        artifact_manifest_id=manifest.manifest_id,
        artifact_manifest_relative_path=relative_path.as_posix(),
        artifact_manifest_sha256=manifest_sha,
    )
    directory = _entry_directory(registry_root, entry_id)
    entry_path = directory / "entry.json"
    wrote_entry = _atomic_write_new(entry_path, canonical_json_bytes(entry))
    registration = _event(
        entry,
        (),
        action="register",
        to_state="candidate",
        evidence=RegistryEvidence(artifact_manifest_sha256=manifest_sha),
    )
    wrote_event = _atomic_write_new(
        _event_path(directory, registration),
        canonical_json_bytes(registration),
    )
    loaded = load_registry_entry(entry_path)
    return RegistryMutationResult(
        entry_path=entry_path,
        entry_id=str(entry_id),
        artifact_id=str(entry.artifact_id),
        state=loaded.state,
        event_count=len(loaded.events),
        status="written" if wrote_entry or wrote_event else "already_current",
    )


def accept_development_candidate(
    entry_path: Path,
    artifact_root: Path,
) -> RegistryMutationResult:
    """Promote a candidate only to the development-accepted state."""

    loaded = load_registry_entry(entry_path)
    if loaded.state == "development_accepted":
        return RegistryMutationResult(
            entry_path=entry_path,
            entry_id=str(loaded.entry.entry_id),
            artifact_id=str(loaded.entry.artifact_id),
            state=loaded.state,
            event_count=len(loaded.events),
            status="already_current",
        )
    artifact_path = artifact_root / Path(loaded.entry.artifact_manifest_relative_path)
    artifact = load_model_artifact(artifact_path, artifact_root).manifest
    if (
        sha256_bytes(artifact_path.read_bytes())
        != loaded.entry.artifact_manifest_sha256
        or artifact.artifact_id != loaded.entry.artifact_id
        or artifact.model_id != loaded.entry.model_id
    ):
        raise ModelArtifactError(
            ArtifactFailureCode.PROVENANCE_MISMATCH,
            "registry entry does not match its verified artifact",
        )
    event = _event(
        loaded.entry,
        loaded.events,
        action="accept_development",
        to_state="development_accepted",
        evidence=RegistryEvidence(
            artifact_manifest_sha256=loaded.entry.artifact_manifest_sha256,
            assessment_manifest_sha256=(artifact.provenance.assessment_manifest_sha256),
        ),
    )
    wrote = _atomic_write_new(
        _event_path(entry_path.parent, event),
        canonical_json_bytes(event),
    )
    updated = load_registry_entry(entry_path)
    return RegistryMutationResult(
        entry_path=entry_path,
        entry_id=str(updated.entry.entry_id),
        artifact_id=str(updated.entry.artifact_id),
        state=updated.state,
        event_count=len(updated.events),
        status="written" if wrote else "already_current",
    )


def reject_registry_entry(
    entry_path: Path,
    *,
    reason: str,
) -> RegistryMutationResult:
    """Append an immutable rejection event from an eligible non-active state."""

    loaded = load_registry_entry(entry_path)
    event = _event(
        loaded.entry,
        loaded.events,
        action="reject",
        to_state="rejected",
        evidence=RegistryEvidence(
            artifact_manifest_sha256=loaded.entry.artifact_manifest_sha256,
            rejection_reason=reason,
        ),
    )
    wrote = _atomic_write_new(
        _event_path(entry_path.parent, event),
        canonical_json_bytes(event),
    )
    updated = load_registry_entry(entry_path)
    return RegistryMutationResult(
        entry_path=entry_path,
        entry_id=str(updated.entry.entry_id),
        artifact_id=str(updated.entry.artifact_id),
        state=updated.state,
        event_count=len(updated.events),
        status="written" if wrote else "already_current",
    )


def request_active_promotion(entry_path: Path) -> None:
    """Fail closed until typed one-time final-test evidence exists."""

    loaded = load_registry_entry(entry_path)
    _event(
        loaded.entry,
        loaded.events,
        action="activate",
        to_state="active",
        evidence=RegistryEvidence(
            artifact_manifest_sha256=loaded.entry.artifact_manifest_sha256
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register a verified model artifact without activating it."
    )
    parser.add_argument("--artifact-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--registry-root", type=Path, default=Path("artifacts/registry")
    )
    parser.add_argument("--accept-development", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = register_model_artifact(
            arguments.artifact_manifest,
            arguments.artifact_root,
            arguments.registry_root,
        )
        if arguments.accept_development:
            result = accept_development_candidate(
                result.entry_path,
                arguments.artifact_root,
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    serialized["entry_path"] = str(result.entry_path)
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
