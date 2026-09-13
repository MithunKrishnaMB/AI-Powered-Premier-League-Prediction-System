"""Tests for deterministic Step 4.2 component serialization and loading."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import pl_platform.registry.serialization as serialization_module
from pl_platform.evaluation.catboost_model import CatBoostParameters
from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ModelArtifactError,
    canonical_json_bytes,
)
from pl_platform.registry.serialization import (
    ModelArtifactMaterializationResult,
    _model_json_payload,
    load_model_artifact,
    main,
    materialize_selected_model_artifact,
)
from pl_platform.training.materialize import TrainingMaterializationResult
from tests.unit.evaluation.helpers import complete_corpus
from tests.unit.registry.helpers import (
    artifact_provenance,
    make_fitted_classifier,
    write_artifact,
)


def test_catboost_json_removes_volatile_metadata_deterministically() -> None:
    first = _model_json_payload(make_fitted_classifier(), "model-id")
    second = _model_json_payload(make_fitted_classifier(), "model-id")
    payload = json.loads(first)

    assert first == second
    assert first == canonical_json_bytes(payload)
    assert payload["model_info"]["model_guid"] == "model-id"
    assert payload["model_info"]["train_finish_time"] == "1970-01-01T00:00:00Z"


def test_artifact_loader_verifies_and_reloads_required_components(
    tmp_path: Path,
) -> None:
    manifest_path = write_artifact(tmp_path)

    loaded = load_model_artifact(manifest_path, tmp_path)

    assert loaded.classifier.diagnostics.tree_count == 200
    assert loaded.classifier.diagnostics.predictor_count == 175
    assert loaded.preprocessor.metadata.fitted_state == "none"
    assert loaded.manifest.model.calibration.strategy == "identity"


@pytest.mark.parametrize("kind", ("file", "directory"))
def test_artifact_loader_rejects_unknown_paths(tmp_path: Path, kind: str) -> None:
    manifest_path = write_artifact(tmp_path)
    undeclared = manifest_path.parent / "undeclared"
    if kind == "file":
        undeclared.write_bytes(b"undeclared")
    else:
        undeclared.mkdir()

    with pytest.raises(ModelArtifactError) as error:
        load_model_artifact(manifest_path, tmp_path)

    assert error.value.code == ArtifactFailureCode.PATH_INVALID


@pytest.mark.parametrize("component", ("preprocessor.json", "classifier.json"))
def test_artifact_loader_rejects_missing_and_changed_components(
    tmp_path: Path,
    component: str,
) -> None:
    manifest_path = write_artifact(tmp_path)
    path = next(manifest_path.parent.rglob(component))
    original = path.read_bytes()
    path.unlink()
    with pytest.raises(ModelArtifactError) as missing:
        load_model_artifact(manifest_path, tmp_path)
    assert missing.value.code == ArtifactFailureCode.COMPONENT_MISSING

    path.write_bytes(original + b" ")
    with pytest.raises(ModelArtifactError) as changed:
        load_model_artifact(manifest_path, tmp_path)
    assert changed.value.code == ArtifactFailureCode.COMPONENT_SIZE_MISMATCH


def test_materializer_writes_reloads_and_reuses_deterministic_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = artifact_provenance()
    training_result = TrainingMaterializationResult(
        training_rows_path=tmp_path / "training.jsonl",
        manifest_path=tmp_path / "training-manifest.json",
        training_row_count=4180,
        training_sha256=provenance.training_manifest.training_sha256,
        status="already_current",
    )
    parameters = CatBoostParameters(
        id="catboost-depth6-regularized",
        iterations=200,
        depth=6,
        learning_rate=0.05,
        l2_leaf_reg=10.0,
    )
    fitted = make_fitted_classifier()
    monkeypatch.setattr(
        serialization_module, "materialize_model_assessment", lambda *args: None
    )
    monkeypatch.setattr(
        serialization_module,
        "materialize_training_dataset",
        lambda *args: training_result,
    )
    monkeypatch.setattr(
        serialization_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), provenance.training_manifest),
    )
    monkeypatch.setattr(serialization_module, "_provenance", lambda *args: provenance)
    monkeypatch.setattr(
        serialization_module,
        "load_catboost_tuning_dataset",
        lambda *args: (
            (),
            SimpleNamespace(
                candidates=(SimpleNamespace(parameters=parameters),),
            ),
        ),
    )
    monkeypatch.setattr(
        serialization_module, "fit_catboost_classifier", lambda *args: fitted
    )
    monkeypatch.setattr(
        serialization_module,
        "_probabilities",
        lambda classifier, examples: np.zeros((len(examples), 3)),
    )
    arguments = (
        tmp_path / "historical.json",
        tmp_path / "teams.json",
        tmp_path / "seasons.json",
        tmp_path / "data",
        tmp_path / "artifacts",
    )

    first = materialize_selected_model_artifact(*arguments)
    second = materialize_selected_model_artifact(*arguments)

    assert first.status == "written"
    assert second.status == "already_current"
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.training_row_count == 30
    assert first.round_trip_max_abs_probability_delta == 0.0


def test_materializer_rejects_training_provenance_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = artifact_provenance()
    changed = provenance.training_manifest.model_copy(
        update={"training_sha256": "0" * 64}
    )
    monkeypatch.setattr(
        serialization_module, "materialize_model_assessment", lambda *args: None
    )
    monkeypatch.setattr(
        serialization_module,
        "materialize_training_dataset",
        lambda *args: SimpleNamespace(
            training_rows_path=tmp_path / "rows",
            manifest_path=tmp_path / "manifest",
        ),
    )
    monkeypatch.setattr(
        serialization_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), changed),
    )
    monkeypatch.setattr(serialization_module, "_provenance", lambda *args: provenance)

    with pytest.raises(ModelArtifactError) as error:
        materialize_selected_model_artifact(
            tmp_path / "historical",
            tmp_path / "teams",
            tmp_path / "seasons",
            tmp_path / "data",
            tmp_path / "artifacts",
        )
    assert error.value.code == ArtifactFailureCode.PROVENANCE_MISMATCH


def test_serialization_cli_reports_success_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = ModelArtifactMaterializationResult(
        manifest_path=tmp_path / "manifest.json",
        model_id="model",
        artifact_id="artifact",
        manifest_id="manifest",
        manifest_sha256="a" * 64,
        preprocessor_sha256="b" * 64,
        classifier_sha256="c" * 64,
        training_row_count=3800,
        round_trip_max_abs_probability_delta=0.0,
        status="written",
    )
    monkeypatch.setattr(
        serialization_module,
        "materialize_selected_model_artifact",
        lambda *args: expected,
    )
    arguments = [
        "--manifest",
        "manifest.json",
        "--teams",
        "teams.json",
        "--seasons",
        "seasons.json",
    ]

    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["model_id"] == "model"

    def fail(*args: object) -> ModelArtifactMaterializationResult:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_INVALID,
            "invalid",
        )

    monkeypatch.setattr(
        serialization_module,
        "materialize_selected_model_artifact",
        fail,
    )
    with pytest.raises(SystemExit):
        main(arguments)
