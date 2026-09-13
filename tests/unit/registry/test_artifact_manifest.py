"""Tests for the Step 4.1 manifest, identities and compatibility rules."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ArtifactRuntimeEnvironment,
    ComponentIntegrity,
    ModelArtifactError,
    ModelArtifactManifest,
    build_model_artifact_manifest,
    canonical_json_bytes,
    deterministic_artifact_id,
    deterministic_component_id,
    deterministic_manifest_id,
    deterministic_selected_model_id,
    load_model_artifact_manifest,
    model_artifact_paths,
    sha256_bytes,
)
from tests.unit.registry.helpers import artifact_provenance


def _manifest() -> ModelArtifactManifest:
    return build_model_artifact_manifest(
        artifact_provenance(),
        preprocessor_integrity=ComponentIntegrity(
            byte_count=100,
            sha256="a" * 64,
        ),
        classifier_integrity=ComponentIntegrity(
            byte_count=200,
            sha256="b" * 64,
        ),
    )


def test_manifest_has_stable_distinct_identities_and_selected_policy() -> None:
    first = _manifest()
    second = _manifest()

    assert first == second
    assert (
        len(
            {
                first.model_id,
                first.artifact_id,
                first.manifest_id,
                *(component.component_id for component in first.components),
            }
        )
        == 5
    )
    assert first.model_id == deterministic_selected_model_id(first.provenance)
    assert first.artifact_id == deterministic_artifact_id(
        first.model_id, first.components
    )
    assert first.manifest_id == deterministic_manifest_id(first)
    assert all(
        component.component_id == deterministic_component_id(first.model_id, component)
        for component in first.components
    )
    assert first.model.classifier.configuration.id == "catboost-depth6-regularized"
    assert first.model.classifier.configuration.depth == 6
    assert first.model.calibration.strategy == "identity"
    assert first.model.score_model.status == "not_included"
    assert first.prediction.outcome_order == ("home_win", "draw", "away_win")
    assert first.prediction.produces_scorelines is False


def test_component_bytes_change_only_artifact_and_downstream_identities() -> None:
    original = _manifest()
    changed = build_model_artifact_manifest(
        original.provenance,
        preprocessor_integrity=original.components[0].integrity,
        classifier_integrity=ComponentIntegrity(
            byte_count=201,
            sha256="c" * 64,
        ),
    )

    assert changed.model_id == original.model_id
    assert changed.components[0].component_id == original.components[0].component_id
    assert changed.components[1].component_id != original.components[1].component_id
    assert changed.artifact_id != original.artifact_id
    assert changed.manifest_id != original.manifest_id


def test_canonical_manifest_bytes_and_path_round_trip(tmp_path: Path) -> None:
    manifest = _manifest()
    payload = canonical_json_bytes(manifest)
    paths = model_artifact_paths(tmp_path, manifest)
    paths.manifest.parent.mkdir(parents=True)
    paths.manifest.write_bytes(payload)

    loaded = load_model_artifact_manifest(
        paths.manifest,
        artifact_root=tmp_path,
        check_runtime=False,
    )

    assert loaded == manifest
    assert payload.startswith(b"{\n") and payload.endswith(b"\n")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert sha256_bytes(payload) == sha256_bytes(canonical_json_bytes(loaded))
    assert paths.preprocessor.name == "preprocessor.json"
    assert paths.classifier.name == "classifier.json"


def test_manifest_loader_rejects_noncanonical_bytes_and_wrong_path(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    wrong = tmp_path / "manifest.json"
    wrong.write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )
    with pytest.raises(ModelArtifactError) as noncanonical:
        load_model_artifact_manifest(wrong, check_runtime=False)
    assert noncanonical.value.code == ArtifactFailureCode.MANIFEST_NON_CANONICAL

    wrong.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ModelArtifactError) as misplaced:
        load_model_artifact_manifest(
            wrong,
            artifact_root=tmp_path,
            check_runtime=False,
        )
    assert misplaced.value.code == ArtifactFailureCode.PATH_INVALID


def test_runtime_compatibility_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest()
    paths = model_artifact_paths(tmp_path, manifest)
    paths.manifest.parent.mkdir(parents=True)
    paths.manifest.write_bytes(canonical_json_bytes(manifest))
    incompatible = ArtifactRuntimeEnvironment(
        python_implementation="CPython",
        python_version="3.14.6",
        pointer_width_bits=64,
        catboost_version="1.2.10",
        numpy_version="2.5.3",
        pydantic_version="2.13.5",
        tzdata_version="2026.3",
    )
    from pl_platform.registry.artifact_manifest import assert_runtime_compatible

    with pytest.raises(ModelArtifactError) as error:
        assert_runtime_compatible(manifest, incompatible)
    assert error.value.code == ArtifactFailureCode.RUNTIME_INCOMPATIBLE


@pytest.mark.parametrize(
    "mutation",
    ("extra", "model_id", "component_order", "predictor", "outcome"),
)
def test_manifest_rejects_unknown_fields_and_identity_contract_drift(
    mutation: str,
) -> None:
    payload = _manifest().model_dump(mode="json")
    if mutation == "extra":
        payload["registry_state"] = "active"
    elif mutation == "model_id":
        payload["model_id"] = "00000000-0000-0000-0000-000000000001"
    elif mutation == "component_order":
        payload["components"] = list(reversed(payload["components"]))
    elif mutation == "predictor":
        payload["predictors"]["predictor_schema"]["predictor_count"] -= 1
    else:
        payload["prediction"]["outcome_order"] = [
            "away_win",
            "draw",
            "home_win",
        ]

    with pytest.raises(ValidationError):
        ModelArtifactManifest.model_validate(payload)


def test_manifest_wraps_contract_validation_failure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"manifest_schema_version":2}', encoding="utf-8")

    with pytest.raises(ModelArtifactError) as error:
        load_model_artifact_manifest(path, check_runtime=False)

    assert error.value.code == ArtifactFailureCode.MANIFEST_INVALID


def test_manifest_wraps_missing_file_failure(tmp_path: Path) -> None:
    with pytest.raises(ModelArtifactError) as error:
        load_model_artifact_manifest(
            tmp_path / "missing.json",
            check_runtime=False,
        )

    assert error.value.code == ArtifactFailureCode.MANIFEST_INVALID
