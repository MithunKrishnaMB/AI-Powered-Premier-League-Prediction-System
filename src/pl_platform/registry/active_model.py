"""Read-only, deterministic resolution of the current active model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

import catboost as _catboost  # type: ignore[import-untyped]

from pl_platform.registry.artifact_manifest import (
    CLASSIFIER_COMPONENT_PATH,
    PREPROCESSOR_COMPONENT_PATH,
    SELECTED_CONFIGURATION_ID,
    ArtifactFailureCode,
    ModelArtifactError,
    canonical_json_bytes,
    sha256_bytes,
)
from pl_platform.registry.registry import (
    LoadedRegistryEntry,
    RegistryEntry,
    RegistryState,
    load_registry_entry,
)
from pl_platform.registry.serialization import LoadedModelArtifact, load_model_artifact


class ActiveModelFailureCode(StrEnum):
    """Stable failure categories exposed by the active-model read boundary."""

    NO_ACTIVE_MODEL = "no_active_model"
    AMBIGUOUS_ACTIVE_MODELS = "ambiguous_active_models"
    MALFORMED_REGISTRY_HISTORY = "malformed_registry_history"
    ARTIFACT_MISSING = "artifact_missing"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    UNSUPPORTED_MODEL_COMPONENT = "unsupported_model_component"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    NON_CANONICAL_ARTIFACT = "non_canonical_artifact"


class ActiveModelLoadError(RuntimeError):
    """The current active model could not be resolved without ambiguity."""

    def __init__(
        self,
        code: ActiveModelFailureCode,
        message: str,
        *,
        entry_id: UUID | None = None,
    ) -> None:
        self.code = code
        self.entry_id = entry_id
        entry_suffix = f" ({entry_id})" if entry_id is not None else ""
        super().__init__(f"{code.value}{entry_suffix}: {message}")


@dataclass(frozen=True, slots=True)
class VerifiedRegistryEntry:
    """One immutable registry head produced from verified append-only history."""

    entry_path: Path
    entry: RegistryEntry
    state: RegistryState
    event_count: int
    head_event_id: UUID
    head_event_sha256: str


class RegistryHistorySource(Protocol):
    """Read-only source of entries whose complete histories have been verified."""

    def load_entries(self, registry_root: Path) -> tuple[VerifiedRegistryEntry, ...]:
        """Return a deterministic snapshot of every verified registry entry."""


@dataclass(frozen=True, slots=True)
class FilesystemRegistryHistorySource:
    """Derive registry heads from canonical filesystem entry/event histories."""

    def load_entries(self, registry_root: Path) -> tuple[VerifiedRegistryEntry, ...]:
        entries_directory = registry_root / "v1" / "entries"
        if not registry_root.exists():
            if registry_root.is_symlink():
                _malformed("registry root is a broken symbolic link")
            return ()
        _require_directory(registry_root, "registry root")
        _require_exact_children(registry_root, {"v1"}, "registry root")
        version_directory = registry_root / "v1"
        _require_directory(version_directory, "registry version directory")
        _require_exact_children(version_directory, {"entries"}, "registry version")
        _require_directory(entries_directory, "registry entries directory")

        entry_directories = tuple(
            sorted(entries_directory.iterdir(), key=lambda path: path.name)
        )
        snapshots: list[VerifiedRegistryEntry] = []
        for directory in entry_directories:
            if directory.is_symlink() or not directory.is_dir():
                _malformed("registry entries must be ordinary directories")
            try:
                directory_id = UUID(directory.name)
            except ValueError as exc:
                raise ActiveModelLoadError(
                    ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY,
                    "registry entry directory name is not a canonical UUID",
                ) from exc
            if directory.name != str(directory_id):
                _malformed("registry entry directory UUID is not canonical")
            loaded = _load_history(directory / "entry.json")
            if loaded.entry.entry_id != directory_id:
                _malformed(
                    "registry entry directory does not match its entry identity",
                    entry_id=loaded.entry.entry_id,
                )
            head = loaded.events[-1]
            snapshots.append(
                VerifiedRegistryEntry(
                    entry_path=directory / "entry.json",
                    entry=loaded.entry,
                    state=loaded.state,
                    event_count=len(loaded.events),
                    head_event_id=head.event_id,
                    head_event_sha256=sha256_bytes(canonical_json_bytes(head)),
                )
            )
        return tuple(snapshots)


@dataclass(frozen=True, slots=True)
class LoadedActiveModel:
    """The single active registry head and its fully verified loaded artifact."""

    registry: VerifiedRegistryEntry
    artifact: LoadedModelArtifact


def _malformed(message: str, *, entry_id: UUID | None = None) -> None:
    raise ActiveModelLoadError(
        ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY,
        message,
        entry_id=entry_id,
    )


def _require_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        _malformed(f"{label} is missing or is not an ordinary directory")


def _require_exact_children(path: Path, expected: set[str], label: str) -> None:
    try:
        children = {child.name for child in path.iterdir()}
    except OSError as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY,
            f"{label} is unreadable",
        ) from exc
    if children != expected:
        _malformed(f"{label} contains an unexpected or missing path")


def _load_history(entry_path: Path) -> LoadedRegistryEntry:
    try:
        return load_registry_entry(entry_path)
    except (OSError, ModelArtifactError) as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY,
            "registry entry or event history is invalid",
        ) from exc


_ARTIFACT_FAILURE_MAPPING: Mapping[ArtifactFailureCode, ActiveModelFailureCode] = {
    ArtifactFailureCode.MANIFEST_INVALID: ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
    ArtifactFailureCode.MANIFEST_NON_CANONICAL: (
        ActiveModelFailureCode.NON_CANONICAL_ARTIFACT
    ),
    ArtifactFailureCode.IDENTITY_MISMATCH: ActiveModelFailureCode.PROVENANCE_MISMATCH,
    ArtifactFailureCode.PATH_INVALID: (
        ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT
    ),
    ArtifactFailureCode.COMPONENT_MISSING: ActiveModelFailureCode.ARTIFACT_MISSING,
    ArtifactFailureCode.COMPONENT_SIZE_MISMATCH: (
        ActiveModelFailureCode.CHECKSUM_MISMATCH
    ),
    ArtifactFailureCode.COMPONENT_CHECKSUM_MISMATCH: (
        ActiveModelFailureCode.CHECKSUM_MISMATCH
    ),
    ArtifactFailureCode.COMPONENT_NON_CANONICAL: (
        ActiveModelFailureCode.NON_CANONICAL_ARTIFACT
    ),
    ArtifactFailureCode.RUNTIME_INCOMPATIBLE: (
        ActiveModelFailureCode.RUNTIME_INCOMPATIBLE
    ),
    ArtifactFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE: (
        ActiveModelFailureCode.SCHEMA_INCOMPATIBLE
    ),
    ArtifactFailureCode.OUTCOME_ORDER_INCOMPATIBLE: (
        ActiveModelFailureCode.SCHEMA_INCOMPATIBLE
    ),
    ArtifactFailureCode.PROVENANCE_MISMATCH: (
        ActiveModelFailureCode.PROVENANCE_MISMATCH
    ),
    ArtifactFailureCode.POLICY_MISMATCH: (
        ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT
    ),
    ArtifactFailureCode.REGISTRY_TRANSITION_INVALID: (
        ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY
    ),
    ArtifactFailureCode.FINAL_TEST_EVIDENCE_REQUIRED: (
        ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY
    ),
}


def _artifact_error(error: ModelArtifactError, entry_id: UUID) -> ActiveModelLoadError:
    return ActiveModelLoadError(
        _ARTIFACT_FAILURE_MAPPING[error.code],
        "active artifact verification failed",
        entry_id=entry_id,
    )


def _manifest_path(snapshot: VerifiedRegistryEntry, artifact_root: Path) -> Path:
    relative = Path(snapshot.entry.artifact_manifest_relative_path)
    path = artifact_root / relative
    try:
        path.resolve().relative_to(artifact_root.resolve())
    except (OSError, ValueError) as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
            "active artifact manifest path escapes the artifact root",
            entry_id=snapshot.entry.entry_id,
        ) from exc
    return path


def _verify_registry_artifact_link(
    snapshot: VerifiedRegistryEntry,
    artifact_root: Path,
) -> tuple[Path, bytes]:
    manifest_path = _manifest_path(snapshot, artifact_root)
    component_paths = (
        manifest_path.parent / Path(PREPROCESSOR_COMPONENT_PATH),
        manifest_path.parent / Path(CLASSIFIER_COMPONENT_PATH),
    )
    if manifest_path.is_symlink() or any(path.is_symlink() for path in component_paths):
        raise ActiveModelLoadError(
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
            "active artifact paths must not be symbolic links",
            entry_id=snapshot.entry.entry_id,
        )
    if not manifest_path.is_file():
        raise ActiveModelLoadError(
            ActiveModelFailureCode.ARTIFACT_MISSING,
            "active artifact manifest is missing",
            entry_id=snapshot.entry.entry_id,
        )
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.ARTIFACT_MISSING,
            "active artifact manifest is unreadable",
            entry_id=snapshot.entry.entry_id,
        ) from exc
    if sha256_bytes(manifest_bytes) != snapshot.entry.artifact_manifest_sha256:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.CHECKSUM_MISMATCH,
            "registry and artifact manifest checksums differ",
            entry_id=snapshot.entry.entry_id,
        )
    return manifest_path, manifest_bytes


def _assert_supported_chain(
    snapshot: VerifiedRegistryEntry,
    loaded: LoadedModelArtifact,
) -> None:
    entry = snapshot.entry
    manifest = loaded.manifest
    if (
        manifest.model_id != entry.model_id
        or manifest.artifact_id != entry.artifact_id
        or manifest.manifest_id != entry.artifact_manifest_id
    ):
        raise ActiveModelLoadError(
            ActiveModelFailureCode.PROVENANCE_MISMATCH,
            "active registry identities do not match the loaded artifact",
            entry_id=entry.entry_id,
        )
    if manifest.prediction.outcome_order != ("home_win", "draw", "away_win"):
        raise ActiveModelLoadError(
            ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
            "active artifact outcome order is unsupported",
            entry_id=entry.entry_id,
        )
    predictor_schema = manifest.predictors.predictor_schema
    if (
        predictor_schema.id != "epl-pre-match"
        or predictor_schema.version != 2
        or predictor_schema.predictor_count != 175
        or loaded.preprocessor.predictor_names != predictor_schema.predictor_names
        or loaded.preprocessor.predictor_names_sha256
        != predictor_schema.predictor_names_sha256
        or loaded.classifier.predictor_names != predictor_schema.predictor_names
    ):
        raise ActiveModelLoadError(
            ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
            "active predictor or preprocessor schema is unsupported",
            entry_id=entry.entry_id,
        )
    classifier = manifest.model.classifier
    components = tuple(
        (component.role, component.relative_path) for component in manifest.components
    )
    if (
        classifier.family != "catboost_multiclass"
        or classifier.configuration.id != SELECTED_CONFIGURATION_ID
        or classifier.configuration.iterations != 200
        or classifier.configuration.depth != 6
        or classifier.configuration.learning_rate != 0.05
        or classifier.configuration.l2_leaf_reg != 10.0
        or manifest.model.preprocessing.fitted_state != "none"
        or manifest.model.calibration.strategy != "identity"
        or manifest.model.score_model.status != "not_included"
        or manifest.model.score_model.scoreline_capability is not False
        or manifest.prediction.produces_scorelines is not False
        or components
        != (
            ("preprocessor", PREPROCESSOR_COMPONENT_PATH),
            ("classifier", CLASSIFIER_COMPONENT_PATH),
        )
    ):
        raise ActiveModelLoadError(
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
            "active model family or component policy is unsupported",
            entry_id=entry.entry_id,
        )


def load_current_active_model(
    *,
    registry_root: Path,
    artifact_root: Path,
    history_source: RegistryHistorySource | None = None,
) -> LoadedActiveModel:
    """Resolve and load exactly one explicitly active, compatible model."""

    source = history_source or FilesystemRegistryHistorySource()
    try:
        snapshots = source.load_entries(registry_root)
    except ActiveModelLoadError:
        raise
    except (OSError, ModelArtifactError, ValueError) as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY,
            "registry history source failed validation",
        ) from exc
    active = tuple(snapshot for snapshot in snapshots if snapshot.state == "active")
    if not active:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.NO_ACTIVE_MODEL,
            "no registry history ends in the active state",
        )
    if len(active) != 1:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.AMBIGUOUS_ACTIVE_MODELS,
            "more than one registry history ends in the active state",
        )
    snapshot = active[0]
    manifest_path, manifest_bytes = _verify_registry_artifact_link(
        snapshot,
        artifact_root,
    )
    try:
        loaded = load_model_artifact(manifest_path, artifact_root)
    except ModelArtifactError as exc:
        raise _artifact_error(exc, snapshot.entry.entry_id) from exc
    except OSError as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.ARTIFACT_MISSING,
            "active artifact became unreadable while loading",
            entry_id=snapshot.entry.entry_id,
        ) from exc
    except _catboost.CatBoostError as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
            "active classifier component could not be loaded",
            entry_id=snapshot.entry.entry_id,
        ) from exc
    try:
        unchanged_manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.ARTIFACT_MISSING,
            "active artifact manifest became unreadable while loading",
            entry_id=snapshot.entry.entry_id,
        ) from exc
    if unchanged_manifest_bytes != manifest_bytes:
        raise ActiveModelLoadError(
            ActiveModelFailureCode.CHECKSUM_MISMATCH,
            "active artifact manifest changed while loading",
            entry_id=snapshot.entry.entry_id,
        )
    _assert_supported_chain(snapshot, loaded)
    return LoadedActiveModel(registry=snapshot, artifact=loaded)
