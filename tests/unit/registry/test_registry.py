"""Tests for append-only Step 4.3 registry states and promotion rules."""

import json
from pathlib import Path

import pytest

import pl_platform.registry.registry as registry_module
from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ModelArtifactError,
)
from pl_platform.registry.registry import (
    accept_development_candidate,
    load_registry_entry,
    main,
    register_model_artifact,
    reject_registry_entry,
    request_active_promotion,
)
from tests.unit.registry.helpers import write_artifact


def test_registration_and_development_acceptance_are_deterministic(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    registry_root = tmp_path / "registry"
    manifest_path = write_artifact(artifact_root)

    first = register_model_artifact(manifest_path, artifact_root, registry_root)
    repeated = register_model_artifact(manifest_path, artifact_root, registry_root)
    accepted = accept_development_candidate(first.entry_path, artifact_root)
    accepted_again = accept_development_candidate(first.entry_path, artifact_root)
    loaded = load_registry_entry(first.entry_path)

    assert first.status == "written"
    assert repeated.status == "already_current"
    assert accepted.state == "development_accepted"
    assert accepted_again.status == "already_current"
    assert tuple(event.to_state for event in loaded.events) == (
        "candidate",
        "development_accepted",
    )
    assert loaded.events[1].previous_event_sha256 is not None


def test_active_promotion_fails_closed_without_final_test_evidence(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    manifest_path = write_artifact(artifact_root)
    registered = register_model_artifact(
        manifest_path,
        artifact_root,
        tmp_path / "registry",
    )
    accept_development_candidate(registered.entry_path, artifact_root)

    with pytest.raises(ModelArtifactError) as error:
        request_active_promotion(registered.entry_path)

    assert error.value.code == ArtifactFailureCode.FINAL_TEST_EVIDENCE_REQUIRED


def test_rejection_is_terminal_and_requires_an_allowed_transition(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    registered = register_model_artifact(
        write_artifact(artifact_root),
        artifact_root,
        tmp_path / "registry",
    )

    rejected = reject_registry_entry(registered.entry_path, reason="review failed")
    assert rejected.state == "rejected"

    with pytest.raises(ModelArtifactError) as error:
        reject_registry_entry(registered.entry_path, reason="again")
    assert error.value.code == ArtifactFailureCode.REGISTRY_TRANSITION_INVALID


def test_registry_loader_rejects_noncanonical_or_broken_event_chain(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    registered = register_model_artifact(
        write_artifact(artifact_root),
        artifact_root,
        tmp_path / "registry",
    )
    accept_development_candidate(registered.entry_path, artifact_root)
    event_path = sorted((registered.entry_path.parent / "events").glob("*.json"))[1]
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    event_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelArtifactError) as error:
        load_registry_entry(registered.entry_path)
    assert error.value.code == ArtifactFailureCode.REGISTRY_TRANSITION_INVALID


def test_registry_loader_rejects_missing_event_directory(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    registered = register_model_artifact(
        write_artifact(artifact_root),
        artifact_root,
        tmp_path / "registry",
    )
    for path in (registered.entry_path.parent / "events").glob("*.json"):
        path.unlink()
    (registered.entry_path.parent / "events").rmdir()

    with pytest.raises(ModelArtifactError) as error:
        load_registry_entry(registered.entry_path)
    assert error.value.code == ArtifactFailureCode.REGISTRY_TRANSITION_INVALID


def test_registry_loader_rejects_undeclared_entry_path(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    registered = register_model_artifact(
        write_artifact(artifact_root),
        artifact_root,
        tmp_path / "registry",
    )
    (registered.entry_path.parent / "undeclared").write_bytes(b"undeclared")

    with pytest.raises(ModelArtifactError) as error:
        load_registry_entry(registered.entry_path)

    assert error.value.code == ArtifactFailureCode.REGISTRY_TRANSITION_INVALID


def test_registry_cli_reports_success_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_root = tmp_path / "artifacts"
    manifest_path = write_artifact(artifact_root)
    arguments = [
        "--artifact-manifest",
        str(manifest_path),
        "--artifact-root",
        str(artifact_root),
        "--registry-root",
        str(tmp_path / "registry"),
        "--accept-development",
    ]

    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "development_accepted"

    monkeypatch.setattr(
        registry_module,
        "register_model_artifact",
        lambda *args: (_ for _ in ()).throw(ValueError("invalid registry")),
    )
    with pytest.raises(SystemExit):
        main(arguments)
