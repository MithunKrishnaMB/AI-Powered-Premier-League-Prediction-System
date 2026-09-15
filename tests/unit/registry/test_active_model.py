"""Tests for deterministic, read-only Step 7.1 active-model loading."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import catboost as _catboost  # type: ignore[import-untyped]
import pytest

import pl_platform.registry.active_model as active_model_module
from pl_platform.registry.active_model import (
    ActiveModelFailureCode,
    ActiveModelLoadError,
    FilesystemRegistryHistorySource,
    VerifiedRegistryEntry,
    load_current_active_model,
)
from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ModelArtifactError,
    canonical_json_bytes,
    sha256_bytes,
)
from pl_platform.registry.registry import (
    RegistryState,
    accept_development_candidate,
    load_registry_entry,
    register_model_artifact,
)
from pl_platform.registry.serialization import load_model_artifact
from tests.unit.registry.helpers import write_artifact


class SyntheticHistorySource:
    """Test-only source; it never writes an active registry event."""

    def __init__(self, *entries: VerifiedRegistryEntry) -> None:
        self.entries = entries

    def load_entries(self, registry_root: Path) -> tuple[VerifiedRegistryEntry, ...]:
        del registry_root
        return self.entries


def _snapshot(entry_path: Path, *, state: RegistryState) -> VerifiedRegistryEntry:
    loaded = load_registry_entry(entry_path)
    head = loaded.events[-1]
    return VerifiedRegistryEntry(
        entry_path=entry_path,
        entry=loaded.entry,
        state=state,
        event_count=len(loaded.events),
        head_event_id=head.event_id,
        head_event_sha256=sha256_bytes(canonical_json_bytes(head)),
    )


def _accepted_registry(tmp_path: Path) -> tuple[Path, Path, Path]:
    artifact_root = tmp_path / "artifacts"
    registry_root = tmp_path / "registry"
    manifest_path = write_artifact(artifact_root)
    registered = register_model_artifact(
        manifest_path,
        artifact_root,
        registry_root,
    )
    accept_development_candidate(registered.entry_path, artifact_root)
    return artifact_root, registry_root, registered.entry_path


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_missing_and_development_accepted_registries_have_no_active_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("a non-active artifact must not be loaded")

    monkeypatch.setattr(active_model_module, "load_model_artifact", unexpected_load)
    with pytest.raises(ActiveModelLoadError) as missing:
        load_current_active_model(
            registry_root=tmp_path / "missing-registry",
            artifact_root=tmp_path / "artifacts",
        )
    assert missing.value.code == ActiveModelFailureCode.NO_ACTIVE_MODEL

    artifact_root, registry_root, _ = _accepted_registry(tmp_path)
    with pytest.raises(ActiveModelLoadError) as accepted:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
        )
    assert accepted.value.code == ActiveModelFailureCode.NO_ACTIVE_MODEL


def test_filesystem_reader_derives_state_from_complete_event_history(
    tmp_path: Path,
) -> None:
    _, registry_root, entry_path = _accepted_registry(tmp_path)

    snapshots = FilesystemRegistryHistorySource().load_entries(registry_root)

    assert len(snapshots) == 1
    assert snapshots[0].entry_path == entry_path
    assert snapshots[0].state == "development_accepted"
    assert snapshots[0].event_count == 2
    assert len(snapshots[0].head_event_sha256) == 64


def test_filesystem_reader_rejects_malformed_layout_and_history(
    tmp_path: Path,
) -> None:
    malformed_root = tmp_path / "malformed"
    malformed_root.mkdir()
    (malformed_root / "unexpected").mkdir()
    with pytest.raises(ActiveModelLoadError) as layout:
        FilesystemRegistryHistorySource().load_entries(malformed_root)
    assert layout.value.code == ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY

    _, registry_root, entry_path = _accepted_registry(tmp_path / "history")
    event_path = sorted((entry_path.parent / "events").glob("*.json"))[-1]
    event_path.write_bytes(event_path.read_bytes() + b" ")
    with pytest.raises(ActiveModelLoadError) as history:
        FilesystemRegistryHistorySource().load_entries(registry_root)
    assert history.value.code == ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY


def test_history_source_failure_has_stable_malformed_history_code(
    tmp_path: Path,
) -> None:
    class InvalidHistorySource:
        def load_entries(
            self,
            registry_root: Path,
        ) -> tuple[VerifiedRegistryEntry, ...]:
            del registry_root
            raise ValueError("invalid synthetic source")

    with pytest.raises(ActiveModelLoadError) as error:
        load_current_active_model(
            registry_root=tmp_path / "registry",
            artifact_root=tmp_path / "artifacts",
            history_source=InvalidHistorySource(),
        )
    assert error.value.code == ActiveModelFailureCode.MALFORMED_REGISTRY_HISTORY


def test_synthetic_active_snapshot_loads_the_complete_real_artifact_read_only(
    tmp_path: Path,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")
    before = _tree_bytes(tmp_path)

    loaded = load_current_active_model(
        registry_root=registry_root,
        artifact_root=artifact_root,
        history_source=SyntheticHistorySource(active),
    )

    assert loaded.registry.state == "active"
    assert loaded.artifact.manifest.model.classifier.configuration.depth == 6
    assert loaded.artifact.manifest.model.calibration.strategy == "identity"
    assert loaded.artifact.manifest.prediction.outcome_order == (
        "home_win",
        "draw",
        "away_win",
    )
    assert loaded.artifact.manifest.prediction.produces_scorelines is False
    assert loaded.artifact.preprocessor.metadata.fitted_state == "none"
    assert loaded.artifact.classifier.diagnostics.predictor_count == 175
    assert _tree_bytes(tmp_path) == before


def test_multiple_synthetic_active_snapshots_fail_before_artifact_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")

    def unexpected_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("ambiguous active artifacts must not be loaded")

    monkeypatch.setattr(active_model_module, "load_model_artifact", unexpected_load)
    with pytest.raises(ActiveModelLoadError) as error:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active, active),
        )
    assert error.value.code == ActiveModelFailureCode.AMBIGUOUS_ACTIVE_MODELS


def test_active_registry_manifest_checksum_and_identity_must_match(
    tmp_path: Path,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")
    wrong_checksum = replace(
        active,
        entry=active.entry.model_copy(update={"artifact_manifest_sha256": "0" * 64}),
    )
    with pytest.raises(ActiveModelLoadError) as checksum:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(wrong_checksum),
        )
    assert checksum.value.code == ActiveModelFailureCode.CHECKSUM_MISMATCH

    wrong_identity = replace(
        active,
        entry=active.entry.model_copy(
            update={"artifact_manifest_id": active.entry.entry_id}
        ),
    )
    with pytest.raises(ActiveModelLoadError) as provenance:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(wrong_identity),
        )
    assert provenance.value.code == ActiveModelFailureCode.PROVENANCE_MISMATCH


def test_missing_manifest_and_component_have_stable_failure(
    tmp_path: Path,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")
    manifest_path = artifact_root / Path(active.entry.artifact_manifest_relative_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest_path.unlink()
    with pytest.raises(ActiveModelLoadError) as manifest_missing:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert manifest_missing.value.code == ActiveModelFailureCode.ARTIFACT_MISSING

    manifest_path.write_bytes(manifest_bytes)
    (manifest_path.parent / "components" / "classifier.json").unlink()
    with pytest.raises(ActiveModelLoadError) as component_missing:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert component_missing.value.code == ActiveModelFailureCode.ARTIFACT_MISSING


def test_component_checksum_drift_has_stable_failure(tmp_path: Path) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")
    manifest_path = artifact_root / Path(active.entry.artifact_manifest_relative_path)
    component = manifest_path.parent / "components" / "preprocessor.json"
    payload = component.read_bytes()
    component.write_bytes(b" " + payload[1:])

    with pytest.raises(ActiveModelLoadError) as error:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert error.value.code == ActiveModelFailureCode.CHECKSUM_MISMATCH


@pytest.mark.parametrize(
    ("artifact_code", "active_code"),
    (
        (
            ArtifactFailureCode.MANIFEST_INVALID,
            ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
        ),
        (
            ArtifactFailureCode.RUNTIME_INCOMPATIBLE,
            ActiveModelFailureCode.RUNTIME_INCOMPATIBLE,
        ),
        (
            ArtifactFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE,
            ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
        ),
        (
            ArtifactFailureCode.OUTCOME_ORDER_INCOMPATIBLE,
            ActiveModelFailureCode.SCHEMA_INCOMPATIBLE,
        ),
        (
            ArtifactFailureCode.POLICY_MISMATCH,
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
        ),
        (
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            ActiveModelFailureCode.NON_CANONICAL_ARTIFACT,
        ),
    ),
)
def test_lower_level_artifact_failures_have_stable_active_boundary_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_code: ArtifactFailureCode,
    active_code: ActiveModelFailureCode,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")

    def reject(*args: object, **kwargs: object) -> object:
        raise ModelArtifactError(artifact_code, "synthetic artifact rejection")

    monkeypatch.setattr(active_model_module, "load_model_artifact", reject)
    with pytest.raises(ActiveModelLoadError) as error:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert error.value.code == active_code


@pytest.mark.parametrize(
    ("load_error", "active_code"),
    (
        (OSError("unreadable"), ActiveModelFailureCode.ARTIFACT_MISSING),
        (
            _catboost.CatBoostError("unsupported classifier"),
            ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT,
        ),
    ),
)
def test_unreadable_or_unsupported_classifier_load_has_stable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    load_error: Exception,
    active_code: ActiveModelFailureCode,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")

    def reject(*args: object, **kwargs: object) -> object:
        raise load_error

    monkeypatch.setattr(active_model_module, "load_model_artifact", reject)
    with pytest.raises(ActiveModelLoadError) as error:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert error.value.code == active_code


def test_loaded_outcome_and_model_family_are_rechecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root, registry_root, entry_path = _accepted_registry(tmp_path)
    active = _snapshot(entry_path, state="active")
    manifest_path = artifact_root / Path(active.entry.artifact_manifest_relative_path)
    valid = load_model_artifact(manifest_path, artifact_root)
    changed_prediction = valid.manifest.prediction.model_copy(
        update={"outcome_order": ("away_win", "draw", "home_win")}
    )
    incompatible = replace(
        valid,
        manifest=valid.manifest.model_copy(update={"prediction": changed_prediction}),
    )
    monkeypatch.setattr(
        active_model_module,
        "load_model_artifact",
        lambda *args: incompatible,
    )
    with pytest.raises(ActiveModelLoadError) as outcome:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert outcome.value.code == ActiveModelFailureCode.SCHEMA_INCOMPATIBLE

    changed_classifier = valid.manifest.model.classifier.model_copy(
        update={"family": "unsupported_family"}
    )
    changed_model = valid.manifest.model.model_copy(
        update={"classifier": changed_classifier}
    )
    unsupported = replace(
        valid,
        manifest=valid.manifest.model_copy(update={"model": changed_model}),
    )
    monkeypatch.setattr(
        active_model_module,
        "load_model_artifact",
        lambda *args: unsupported,
    )
    with pytest.raises(ActiveModelLoadError) as family:
        load_current_active_model(
            registry_root=registry_root,
            artifact_root=artifact_root,
            history_source=SyntheticHistorySource(active),
        )
    assert family.value.code == ActiveModelFailureCode.UNSUPPORTED_MODEL_COMPONENT
