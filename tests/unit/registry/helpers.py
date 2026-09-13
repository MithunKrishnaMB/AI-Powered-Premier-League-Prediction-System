"""Focused artifact fixtures backed by the verified development manifests."""

from functools import cache
from pathlib import Path

import catboost as _catboost  # type: ignore[import-untyped]
import numpy as np

from pl_platform.evaluation.catboost_model import (
    CatBoostFitDiagnostics,
    FittedCatBoostClassifier,
)
from pl_platform.registry.artifact_manifest import (
    ComponentIntegrity,
    ModelArtifactProvenance,
    build_model_artifact_manifest,
    canonical_json_bytes,
    deterministic_selected_model_id,
    model_artifact_paths,
    sha256_bytes,
)
from pl_platform.registry.serialization import (
    _model_json_payload,
    _preprocessor_payload,
    _provenance,
)

ROOT = Path(__file__).parents[3]


@cache
def artifact_provenance() -> ModelArtifactProvenance:
    return _provenance(ROOT / "data")


def make_fitted_classifier() -> FittedCatBoostClassifier:
    provenance = artifact_provenance()
    names = provenance.training_manifest.predictor_schema.predictor_names
    row = np.arange(len(names), dtype=np.float64)
    matrix = np.stack(
        (
            row,
            row + 1.0,
            row + 2.0,
            row + 0.1,
            row + 1.1,
            row + 2.1,
        )
    )
    targets = np.asarray((0, 1, 2, 0, 1, 2), dtype=np.int64)
    model = _catboost.CatBoostClassifier(
        iterations=200,
        depth=6,
        learning_rate=0.05,
        l2_leaf_reg=10.0,
        loss_function="MultiClass",
        random_seed=20260912,
        thread_count=1,
        task_type="CPU",
        bootstrap_type="No",
        random_strength=0.0,
        grow_policy="SymmetricTree",
        nan_mode="Min",
        allow_writing_files=False,
        logging_level="Silent",
    )
    model.fit(matrix, targets)
    return FittedCatBoostClassifier(
        predictor_names=names,
        model=model,
        diagnostics=CatBoostFitDiagnostics(
            candidate_id="catboost-depth6-regularized",
            tree_count=200,
            predictor_count=len(names),
            training_row_count=6,
        ),
    )


def write_artifact(artifact_root: Path) -> Path:
    provenance = artifact_provenance()
    model_id = deterministic_selected_model_id(provenance)
    preprocessor_bytes = canonical_json_bytes(
        _preprocessor_payload(provenance, str(model_id))
    )
    classifier_bytes = _model_json_payload(
        make_fitted_classifier(),
        str(model_id),
    )
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
    paths = model_artifact_paths(artifact_root, manifest)
    paths.preprocessor.parent.mkdir(parents=True)
    paths.preprocessor.write_bytes(preprocessor_bytes)
    paths.classifier.write_bytes(classifier_bytes)
    paths.manifest.write_bytes(canonical_json_bytes(manifest))
    return paths.manifest
