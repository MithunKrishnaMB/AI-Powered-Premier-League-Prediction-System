"""Serialize and reload the selected deterministic development model artifact."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, cast

import catboost as _catboost  # type: ignore[import-untyped]
import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.advanced_materialize import (
    load_advanced_evaluation_dataset,
)
from pl_platform.evaluation.assessment_materialize import (
    load_model_assessment,
    materialize_model_assessment,
)
from pl_platform.evaluation.catboost_materialize import (
    load_catboost_tuning_dataset,
)
from pl_platform.evaluation.catboost_model import (
    CatBoostFitDiagnostics,
    FittedCatBoostClassifier,
    _CatBoostModel,
    fit_catboost_classifier,
)
from pl_platform.evaluation.logistic import predictor_matrix
from pl_platform.evaluation.materialize import load_evaluation_dataset
from pl_platform.evaluation.test_freeze import load_test_freeze
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    examples_for_seasons,
)
from pl_platform.registry.artifact_manifest import (
    ArtifactFailureCode,
    ComponentIntegrity,
    EvaluationProvenance,
    ModelArtifactError,
    ModelArtifactManifest,
    ModelArtifactProvenance,
    PreprocessingMetadata,
    build_model_artifact_manifest,
    canonical_json_bytes,
    deterministic_selected_model_id,
    load_model_artifact_manifest,
    model_artifact_paths,
    sha256_bytes,
)
from pl_platform.training.materialize import (
    load_training_dataset,
    materialize_training_dataset,
)

MODEL_SERIALIZATION_VERSION: Final = 1


class PreprocessorComponentPayload(BaseModel):
    """Serializable, stateless input transformation contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["pl-platform-ordered-numeric-preprocessor"] = (
        "pl-platform-ordered-numeric-preprocessor"
    )
    schema_version: Literal[1] = 1
    model_id: str
    predictor_schema_id: Literal["epl-pre-match"] = "epl-pre-match"
    predictor_schema_version: Literal[2] = 2
    predictor_names: tuple[str, ...]
    predictor_names_sha256: str
    metadata: PreprocessingMetadata = PreprocessingMetadata()
    output_dtype: Literal["float64"] = "float64"
    classifier_missing_value_policy: Literal["native_nan_min"] = "native_nan_min"


@dataclass(frozen=True, slots=True)
class LoadedModelArtifact:
    manifest: ModelArtifactManifest
    preprocessor: PreprocessorComponentPayload
    classifier: FittedCatBoostClassifier


@dataclass(frozen=True, slots=True)
class ModelArtifactMaterializationResult:
    manifest_path: Path
    model_id: str
    artifact_id: str
    manifest_id: str
    manifest_sha256: str
    preprocessor_sha256: str
    classifier_sha256: str
    training_row_count: int
    round_trip_max_abs_probability_delta: float
    status: Literal["written", "already_current"]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _model_json_payload(
    fitted: FittedCatBoostClassifier,
    model_id: str,
) -> bytes:
    """Export CatBoost JSON after replacing its two volatile metadata values."""

    with tempfile.TemporaryDirectory(prefix="plp-catboost-export-") as directory:
        exported_path = Path(directory) / "model.json"
        fitted.model.save_model(str(exported_path), format="json")
        raw = json.loads(exported_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "CatBoost JSON export must contain one object",
        )
    model_info = raw.get("model_info")
    if not isinstance(model_info, dict):
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "CatBoost JSON export has no model_info object",
        )
    if "model_guid" not in model_info or "train_finish_time" not in model_info:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "CatBoost volatile metadata contract changed",
        )
    model_info["model_guid"] = model_id
    model_info["train_finish_time"] = "1970-01-01T00:00:00Z"
    return canonical_json_bytes(cast(dict[str, object], raw))


def _preprocessor_payload(
    provenance: ModelArtifactProvenance,
    model_id: str,
) -> PreprocessorComponentPayload:
    schema = provenance.training_manifest.predictor_schema
    return PreprocessorComponentPayload(
        model_id=model_id,
        predictor_names=schema.predictor_names,
        predictor_names_sha256=schema.predictor_names_sha256,
    )


def _load_classifier_bytes(
    payload: bytes,
    manifest: ModelArtifactManifest,
) -> FittedCatBoostClassifier:
    with tempfile.TemporaryDirectory(prefix="plp-catboost-load-") as directory:
        path = Path(directory) / "classifier.json"
        path.write_bytes(payload)
        model = _catboost.CatBoostClassifier()
        model.load_model(str(path), format="json")
    typed_model = cast(_CatBoostModel, model)
    classes = tuple(int(value) for value in typed_model.classes_)
    parameters = manifest.model.classifier.configuration
    if (
        classes != (0, 1, 2)
        or typed_model.tree_count_ != parameters.iterations
        or len(typed_model.feature_names_)
        != manifest.predictors.predictor_schema.predictor_count
    ):
        raise ModelArtifactError(
            ArtifactFailureCode.POLICY_MISMATCH,
            "loaded classifier structure does not match the manifest",
        )
    return FittedCatBoostClassifier(
        predictor_names=manifest.predictors.predictor_schema.predictor_names,
        model=typed_model,
        diagnostics=CatBoostFitDiagnostics(
            candidate_id=parameters.id,
            tree_count=typed_model.tree_count_,
            predictor_count=manifest.predictors.predictor_schema.predictor_count,
            training_row_count=sum(
                source.feature_row_count
                for source in (
                    manifest.provenance.training_manifest.source_feature_datasets
                )
                if source.season_id in DEVELOPMENT_SEASONS
            ),
        ),
    )


def _verify_component(
    path: Path,
    expected: ComponentIntegrity,
) -> bytes:
    if not path.is_file():
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_MISSING,
            f"required component is missing: {path.name}",
        )
    payload = path.read_bytes()
    if len(payload) != expected.byte_count:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_SIZE_MISMATCH,
            f"component byte count differs: {path.name}",
        )
    if sha256_bytes(payload) != expected.sha256:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_CHECKSUM_MISMATCH,
            f"component checksum differs: {path.name}",
        )
    return payload


def load_model_artifact(
    manifest_path: Path,
    artifact_root: Path,
) -> LoadedModelArtifact:
    """Verify, compatibility-check and reload every required component."""

    manifest = load_model_artifact_manifest(
        manifest_path,
        artifact_root=artifact_root,
    )
    paths = model_artifact_paths(artifact_root, manifest)
    preprocessor_bytes = _verify_component(
        paths.preprocessor, manifest.components[0].integrity
    )
    classifier_bytes = _verify_component(
        paths.classifier, manifest.components[1].integrity
    )
    expected_files = {
        paths.manifest.resolve(),
        paths.preprocessor.resolve(),
        paths.classifier.resolve(),
    }
    actual_files = {
        candidate.resolve()
        for candidate in paths.directory.rglob("*")
        if candidate.is_file()
    }
    actual_directories = {
        candidate.resolve()
        for candidate in paths.directory.rglob("*")
        if candidate.is_dir()
    }
    expected_directories = {paths.preprocessor.parent.resolve()}
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ModelArtifactError(
            ArtifactFailureCode.PATH_INVALID,
            "artifact directory contains an undeclared path",
        )
    try:
        preprocessor = PreprocessorComponentPayload.model_validate_json(
            preprocessor_bytes
        )
    except ValidationError as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "preprocessor component is invalid",
        ) from exc
    if canonical_json_bytes(preprocessor) != preprocessor_bytes:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "preprocessor component bytes are not canonical",
        )
    schema = manifest.predictors.predictor_schema
    if (
        preprocessor.model_id != str(manifest.model_id)
        or preprocessor.predictor_names != schema.predictor_names
        or preprocessor.predictor_names_sha256 != schema.predictor_names_sha256
    ):
        raise ModelArtifactError(
            ArtifactFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE,
            "preprocessor does not match the manifest predictor schema",
        )
    try:
        parsed_classifier = json.loads(classifier_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "classifier component is not valid UTF-8 JSON",
        ) from exc
    if (
        not isinstance(parsed_classifier, dict)
        or canonical_json_bytes(cast(dict[str, object], parsed_classifier))
        != classifier_bytes
    ):
        raise ModelArtifactError(
            ArtifactFailureCode.COMPONENT_NON_CANONICAL,
            "classifier component bytes are not canonical",
        )
    classifier = _load_classifier_bytes(classifier_bytes, manifest)
    return LoadedModelArtifact(
        manifest=manifest,
        preprocessor=preprocessor,
        classifier=classifier,
    )


def _provenance(data_root: Path) -> ModelArtifactProvenance:
    evaluation_root = data_root / "processed" / "evaluation" / "epl"
    base_directory = evaluation_root / "development-2015-2016_to_2024-2025"
    _, base = load_evaluation_dataset(
        base_directory / "predictions.jsonl",
        base_directory / "dataset-manifest.json",
    )
    catboost_directory = evaluation_root / "catboost-tuning-2015-2016_to_2024-2025"
    _, catboost = load_catboost_tuning_dataset(
        catboost_directory / "selected-predictions.jsonl",
        catboost_directory / "dataset-manifest.json",
    )
    advanced_directory = evaluation_root / "advanced-development-2015-2016_to_2024-2025"
    _, advanced = load_advanced_evaluation_dataset(
        advanced_directory / "predictions.jsonl",
        advanced_directory / "dataset-manifest.json",
    )
    assessment_path = (
        evaluation_root
        / "model-assessment-2015-2016_to_2024-2025"
        / "assessment-manifest.json"
    )
    assessment = load_model_assessment(assessment_path)
    freeze_path = evaluation_root / "test-2025-2026" / "freeze-manifest.json"
    freeze = load_test_freeze(freeze_path)
    expected_base_id = "probabilistic-development-evaluation-v1-2015-2016-to-2024-2025"
    if base.dataset_id != expected_base_id:
        raise ModelArtifactError(
            ArtifactFailureCode.PROVENANCE_MISMATCH,
            "base evaluation has an unsupported dataset identity",
        )
    return ModelArtifactProvenance(
        development_season_ids=DEVELOPMENT_SEASONS,
        untouched_test_season_ids=("2025-2026",),
        training_manifest_sha256=sha256_bytes(
            canonical_json_bytes(assessment.source_training_manifest)
        ),
        training_manifest=assessment.source_training_manifest,
        evaluations=EvaluationProvenance(
            base_evaluation_dataset_id=(
                "probabilistic-development-evaluation-v1-2015-2016-to-2024-2025"
            ),
            base_evaluation_manifest_sha256=sha256_bytes(
                (base_directory / "dataset-manifest.json").read_bytes()
            ),
            base_predictions_sha256=base.predictions_sha256,
            catboost_tuning_dataset_id=catboost.dataset_id,
            catboost_tuning_manifest_sha256=sha256_bytes(
                (catboost_directory / "dataset-manifest.json").read_bytes()
            ),
            catboost_selected_predictions_sha256=(catboost.selected_predictions_sha256),
            advanced_evaluation_dataset_id=advanced.dataset_id,
            advanced_evaluation_manifest_sha256=sha256_bytes(
                (advanced_directory / "dataset-manifest.json").read_bytes()
            ),
            advanced_predictions_sha256=advanced.predictions_sha256,
        ),
        assessment_manifest_sha256=sha256_bytes(assessment_path.read_bytes()),
        assessment_manifest=assessment,
        untouched_test_freeze_manifest_sha256=sha256_bytes(freeze_path.read_bytes()),
        untouched_test_freeze=freeze,
    )


def _probabilities(
    classifier: FittedCatBoostClassifier,
    examples: Sequence[TrainingExample],
) -> np.ndarray:
    matrix = predictor_matrix(
        tuple(example.predictors for example in examples),
        classifier.predictor_names,
    )
    values = np.asarray(classifier.model.predict_proba(matrix), dtype=np.float64)
    if values.shape != (len(examples), 3) or not np.isfinite(values).all():
        raise ModelArtifactError(
            ArtifactFailureCode.POLICY_MISMATCH,
            "classifier returned invalid development predictions",
        )
    return values


def materialize_selected_model_artifact(
    historical_manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
    artifact_root: Path,
) -> ModelArtifactMaterializationResult:
    """Reverify raw lineage, serialize the selected model and round-trip it."""

    materialize_model_assessment(
        historical_manifest_path,
        team_registry_path,
        season_registry_path,
        data_root,
    )
    training_result = materialize_training_dataset(
        historical_manifest_path,
        team_registry_path,
        season_registry_path,
        data_root,
    )
    examples, training_manifest = load_training_dataset(
        training_result.training_rows_path,
        training_result.manifest_path,
    )
    provenance = _provenance(data_root)
    if training_manifest != provenance.training_manifest:
        raise ModelArtifactError(
            ArtifactFailureCode.PROVENANCE_MISMATCH,
            "current verified training manifest differs from assessment provenance",
        )
    development_examples = examples_for_seasons(examples, DEVELOPMENT_SEASONS)
    parameters = provenance.assessment_manifest.explanations.catboost_candidate_id
    selected = next(
        candidate.parameters
        for candidate in load_catboost_tuning_dataset(
            data_root
            / "processed"
            / "evaluation"
            / "epl"
            / "catboost-tuning-2015-2016_to_2024-2025"
            / "selected-predictions.jsonl",
            data_root
            / "processed"
            / "evaluation"
            / "epl"
            / "catboost-tuning-2015-2016_to_2024-2025"
            / "dataset-manifest.json",
        )[1].candidates
        if candidate.parameters.id == parameters
    )
    fitted = fit_catboost_classifier(
        development_examples,
        training_manifest.predictor_schema.predictor_names,
        selected,
    )
    model_id = deterministic_selected_model_id(provenance)
    preprocessor = _preprocessor_payload(provenance, str(model_id))
    preprocessor_bytes = canonical_json_bytes(preprocessor)
    classifier_bytes = _model_json_payload(fitted, str(model_id))
    manifest = build_model_artifact_manifest(
        provenance,
        preprocessor_integrity=ComponentIntegrity(
            byte_count=len(preprocessor_bytes),
            sha256=sha256_bytes(preprocessor_bytes),
        ),
        classifier_integrity=ComponentIntegrity(
            byte_count=len(classifier_bytes),
            sha256=sha256_bytes(classifier_bytes),
        ),
    )
    manifest_bytes = canonical_json_bytes(manifest)
    paths = model_artifact_paths(artifact_root, manifest)
    is_current = (
        paths.manifest.is_file()
        and paths.preprocessor.is_file()
        and paths.classifier.is_file()
        and paths.manifest.read_bytes() == manifest_bytes
        and paths.preprocessor.read_bytes() == preprocessor_bytes
        and paths.classifier.read_bytes() == classifier_bytes
    )
    if not is_current:
        _atomic_write(paths.preprocessor, preprocessor_bytes)
        _atomic_write(paths.classifier, classifier_bytes)
        _atomic_write(paths.manifest, manifest_bytes)
    loaded = load_model_artifact(paths.manifest, artifact_root)
    before = _probabilities(fitted, development_examples)
    after = _probabilities(loaded.classifier, development_examples)
    maximum_delta = float(np.max(np.abs(before - after)))
    round_trip_tolerance = float(np.finfo(np.float64).eps * 4.0)
    if maximum_delta > round_trip_tolerance:
        raise ModelArtifactError(
            ArtifactFailureCode.POLICY_MISMATCH,
            "serialized classifier changed predictions beyond float64 tolerance",
        )
    return ModelArtifactMaterializationResult(
        manifest_path=paths.manifest,
        model_id=str(manifest.model_id),
        artifact_id=str(manifest.artifact_id),
        manifest_id=str(manifest.manifest_id),
        manifest_sha256=sha256_bytes(manifest_bytes),
        preprocessor_sha256=sha256_bytes(preprocessor_bytes),
        classifier_sha256=sha256_bytes(classifier_bytes),
        training_row_count=len(development_examples),
        round_trip_max_abs_probability_delta=maximum_delta,
        status="already_current" if is_current else "written",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the deterministic selected development model artifact."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--seasons", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = materialize_selected_model_artifact(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
            arguments.artifact_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    serialized["manifest_path"] = str(result.manifest_path)
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
