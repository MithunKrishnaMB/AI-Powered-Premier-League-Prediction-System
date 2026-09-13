"""Strict, deterministic model-artifact layout and manifest contracts."""

from __future__ import annotations

import hashlib
import json
import platform
import struct
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pl_platform.evaluation.assessment_materialize import ModelAssessmentManifest
from pl_platform.evaluation.catboost_model import (
    CATBOOST_METHOD_VERSION,
    CATBOOST_RANDOM_SEED,
    CATBOOST_RUNTIME_VERSION,
    CatBoostParameters,
)
from pl_platform.evaluation.test_freeze import UntouchedTestFreeze
from pl_platform.evaluation.walk_forward import DEVELOPMENT_SEASONS, EXCLUDED_SEASONS
from pl_platform.features.materialize import FeaturePredictorSchema
from pl_platform.training.materialize import TrainingDatasetManifest

MODEL_ARTIFACT_MANIFEST_SCHEMA_VERSION: Final = 1
MODEL_ARTIFACT_LAYOUT_VERSION: Final = 1
MODEL_ARTIFACT_SCHEMA_ID: Final = "pl-platform-model-artifact"
MODEL_ARTIFACT_NAMESPACE: Final = "pl-platform:model-artifact"
SELECTED_CONFIGURATION_ID: Final = "catboost-depth6-regularized"
MANIFEST_FILENAME: Final = "manifest.json"
PREPROCESSOR_COMPONENT_PATH: Final = "components/preprocessor.json"
CLASSIFIER_COMPONENT_PATH: Final = "components/classifier.json"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class ArtifactFailureCode(StrEnum):
    """Stable categories for fail-closed artifact errors."""

    MANIFEST_INVALID = "manifest_invalid"
    MANIFEST_NON_CANONICAL = "manifest_non_canonical"
    IDENTITY_MISMATCH = "identity_mismatch"
    PATH_INVALID = "path_invalid"
    COMPONENT_MISSING = "component_missing"
    COMPONENT_SIZE_MISMATCH = "component_size_mismatch"
    COMPONENT_CHECKSUM_MISMATCH = "component_checksum_mismatch"
    COMPONENT_NON_CANONICAL = "component_non_canonical"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    PREDICTOR_SCHEMA_INCOMPATIBLE = "predictor_schema_incompatible"
    OUTCOME_ORDER_INCOMPATIBLE = "outcome_order_incompatible"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    POLICY_MISMATCH = "policy_mismatch"
    REGISTRY_TRANSITION_INVALID = "registry_transition_invalid"
    FINAL_TEST_EVIDENCE_REQUIRED = "final_test_evidence_required"


class ModelArtifactError(ValueError):
    """An artifact fails a stable validation or compatibility rule."""

    def __init__(self, code: ArtifactFailureCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


class ComponentIntegrity(BaseModel):
    """Exact byte identity supplied by the Step 4.2 serializer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    byte_count: PositiveInt
    sha256: Sha256


class ArtifactComponent(BaseModel):
    """One required, content-addressed artifact file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component_schema_version: Literal[1] = 1
    component_id: UUID
    role: Literal["preprocessor", "classifier"]
    required: Literal[True] = True
    relative_path: str
    format_id: Literal[
        "pl-platform-ordered-numeric-preprocessor-json",
        "catboost-json",
    ]
    format_contract_version: Literal[1] = 1
    media_type: Literal["application/json"] = "application/json"
    integrity: ComponentIntegrity

    @model_validator(mode="after")
    def path_and_format_must_match_role(self) -> Self:
        expected = {
            "preprocessor": (
                PREPROCESSOR_COMPONENT_PATH,
                "pl-platform-ordered-numeric-preprocessor-json",
            ),
            "classifier": (CLASSIFIER_COMPONENT_PATH, "catboost-json"),
        }[self.role]
        if (self.relative_path, self.format_id) != expected:
            raise ValueError("component path or format does not match its role")
        _validate_relative_path(self.relative_path)
        return self


class ArtifactRuntimeRequirements(BaseModel):
    """Exact runtime required by the version-1 classifier artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_implementation: Literal["CPython"] = "CPython"
    python_version: Literal["3.14.7"] = "3.14.7"
    pointer_width_bits: Literal[64] = 64
    catboost_version: Literal["1.2.10"] = CATBOOST_RUNTIME_VERSION
    numpy_version: Literal["2.5.3"] = "2.5.3"
    pydantic_version: Literal["2.13.5"] = "2.13.5"
    tzdata_version: Literal["2026.3"] = "2026.3"
    numerical_dtype: Literal["float64"] = "float64"
    task_type: Literal["CPU"] = "CPU"
    thread_count: Literal[1] = 1


class ArtifactRuntimeEnvironment(BaseModel):
    """Observed local environment used for compatibility checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_implementation: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
    pointer_width_bits: PositiveInt
    catboost_version: str = Field(min_length=1)
    numpy_version: str = Field(min_length=1)
    pydantic_version: str = Field(min_length=1)
    tzdata_version: str = Field(min_length=1)


class PredictorCompatibility(BaseModel):
    """Exact predictor boundary accepted by the serialized preprocessor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    predictor_schema: FeaturePredictorSchema
    order_policy: Literal["exact_manifest_order"] = "exact_manifest_order"
    unknown_predictor_policy: Literal["reject"] = "reject"
    missing_predictor_policy: Literal["reject"] = "reject"


class PredictionContract(BaseModel):
    """The only prediction behavior claimed by this artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: Literal["full_time_three_way_outcome_probability"] = (
        "full_time_three_way_outcome_probability"
    )
    outcome_order: tuple[Literal["home_win"], Literal["draw"], Literal["away_win"]] = (
        "home_win",
        "draw",
        "away_win",
    )
    probability_sum_tolerance: Annotated[
        float, Field(strict=True, ge=1e-12, le=1e-12, allow_inf_nan=False)
    ] = 1e-12
    produces_scorelines: Literal[False] = False


class CatBoostClassifierMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family: Literal["catboost_multiclass"] = "catboost_multiclass"
    method_version: Literal[1] = CATBOOST_METHOD_VERSION
    configuration: CatBoostParameters
    loss_function: Literal["MultiClass"] = "MultiClass"
    random_seed: Literal[20260912] = CATBOOST_RANDOM_SEED
    bootstrap_type: Literal["No"] = "No"
    random_strength: Annotated[
        float, Field(strict=True, ge=0.0, le=0.0, allow_inf_nan=False)
    ] = 0.0
    grow_policy: Literal["SymmetricTree"] = "SymmetricTree"
    nan_mode: Literal["Min"] = "Min"

    @model_validator(mode="after")
    def configuration_must_be_selected_depth_six(self) -> Self:
        expected = CatBoostParameters(
            id=SELECTED_CONFIGURATION_ID,
            iterations=200,
            depth=6,
            learning_rate=0.05,
            l2_leaf_reg=10.0,
        )
        if self.configuration != expected:
            raise ValueError("classifier is not the selected depth-6 configuration")
        return self


class PreprocessingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["ordered_numeric_matrix"] = "ordered_numeric_matrix"
    version: Literal[1] = 1
    fitted_state: Literal["none"] = "none"
    boolean_mapping: tuple[Literal["false=0.0"], Literal["true=1.0"]] = (
        "false=0.0",
        "true=1.0",
    )
    numeric_cast: Literal["numpy_float64"] = "numpy_float64"
    null_mapping: Literal["numpy_nan"] = "numpy_nan"
    predictor_order: Literal["manifest_exact"] = "manifest_exact"
    learned_imputation: Literal[False] = False
    learned_scaling: Literal[False] = False


class IdentityCalibrationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal["identity"] = "identity"
    version: Literal[1] = 1
    parameter_count: Literal[0] = 0
    component_required: Literal[False] = False


class AbsentScoreModelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_included"] = "not_included"
    component_required: Literal[False] = False
    scoreline_capability: Literal[False] = False
    reason: Literal["no_score_model_selected_for_this_artifact"] = (
        "no_score_model_selected_for_this_artifact"
    )


class ModelSpecification(BaseModel):
    """Selected development policy, separate from physical serialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specification_version: Literal[1] = 1
    competition_id: Literal["eng-premier-league"] = "eng-premier-league"
    classifier: CatBoostClassifierMetadata
    preprocessing: PreprocessingMetadata = PreprocessingMetadata()
    calibration: IdentityCalibrationMetadata = IdentityCalibrationMetadata()
    score_model: AbsentScoreModelMetadata = AbsentScoreModelMetadata()


class EvaluationProvenance(BaseModel):
    """Checksums of every development evaluation used by acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_evaluation_dataset_id: Literal[
        "probabilistic-development-evaluation-v1-2015-2016-to-2024-2025"
    ]
    base_evaluation_manifest_sha256: Sha256
    base_predictions_sha256: Sha256
    catboost_tuning_dataset_id: Literal["catboost-tuning-v1-2015-2016-to-2024-2025"]
    catboost_tuning_manifest_sha256: Sha256
    catboost_selected_predictions_sha256: Sha256
    advanced_evaluation_dataset_id: Literal[
        "advanced-evaluation-v1-2015-2016-to-2024-2025"
    ]
    advanced_evaluation_manifest_sha256: Sha256
    advanced_predictions_sha256: Sha256


class ModelArtifactProvenance(BaseModel):
    """Complete training-to-acceptance lineage without test targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    development_season_ids: tuple[str, ...]
    untouched_test_season_ids: tuple[str, ...]
    training_manifest_sha256: Sha256
    training_manifest: TrainingDatasetManifest
    evaluations: EvaluationProvenance
    assessment_manifest_sha256: Sha256
    assessment_manifest: ModelAssessmentManifest
    untouched_test_freeze_manifest_sha256: Sha256
    untouched_test_freeze: UntouchedTestFreeze

    @model_validator(mode="after")
    def lineage_must_be_complete_and_selected(self) -> Self:
        if self.development_season_ids != DEVELOPMENT_SEASONS:
            raise ValueError("artifact has an unsupported development window")
        if self.untouched_test_season_ids != EXCLUDED_SEASONS:
            raise ValueError("artifact has an unsupported untouched-test window")
        if sha256_bytes(canonical_json_bytes(self.training_manifest)) != (
            self.training_manifest_sha256
        ):
            raise ValueError("training manifest checksum does not match embedded bytes")
        if sha256_bytes(canonical_json_bytes(self.assessment_manifest)) != (
            self.assessment_manifest_sha256
        ):
            raise ValueError(
                "assessment manifest checksum does not match embedded bytes"
            )
        if sha256_bytes(canonical_json_bytes(self.untouched_test_freeze)) != (
            self.untouched_test_freeze_manifest_sha256
        ):
            raise ValueError("test-freeze checksum does not match embedded bytes")
        sources = self.assessment_manifest.sources
        evaluation_checksums = (
            self.evaluations.base_evaluation_manifest_sha256,
            self.evaluations.base_predictions_sha256,
            self.evaluations.catboost_tuning_manifest_sha256,
            self.evaluations.catboost_selected_predictions_sha256,
            self.evaluations.advanced_evaluation_manifest_sha256,
            self.evaluations.advanced_predictions_sha256,
        )
        assessment_checksums = (
            sources.base_evaluation_manifest_sha256,
            sources.base_predictions_sha256,
            sources.catboost_tuning_manifest_sha256,
            sources.catboost_selected_predictions_sha256,
            sources.advanced_evaluation_manifest_sha256,
            sources.advanced_predictions_sha256,
        )
        if evaluation_checksums != assessment_checksums:
            raise ValueError("evaluation provenance does not match assessment sources")
        if (
            self.assessment_manifest.source_training_manifest != self.training_manifest
            or sources.training_manifest_sha256 != self.training_manifest_sha256
            or sources.untouched_test_freeze_manifest_sha256
            != self.untouched_test_freeze_manifest_sha256
            or self.untouched_test_freeze.source_training_dataset_id
            != self.training_manifest.dataset_id
            or self.untouched_test_freeze.source_training_sha256
            != self.training_manifest.training_sha256
            or self.untouched_test_freeze.source_training_manifest_sha256
            != self.training_manifest_sha256
        ):
            raise ValueError("training, assessment and freeze provenance disagree")
        if (
            self.assessment_manifest.acceptance.champion_method != "catboost"
            or self.assessment_manifest.explanations.catboost_candidate_id
            != SELECTED_CONFIGURATION_ID
            or self.assessment_manifest.explanations.calibration_selected_strategy
            != "identity"
        ):
            raise ValueError("assessment does not select CatBoost depth-6 identity")
        return self


class ModelArtifactManifest(BaseModel):
    """Canonical contract for one complete, content-addressed model artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_id: Literal["pl-platform-model-artifact"]
    manifest_schema_version: Literal[1]
    layout_version: Literal[1]
    manifest_id: UUID
    model_id: UUID
    artifact_id: UUID
    model: ModelSpecification
    prediction: PredictionContract
    predictors: PredictorCompatibility
    runtime: ArtifactRuntimeRequirements
    provenance: ModelArtifactProvenance
    components: tuple[ArtifactComponent, ArtifactComponent]

    @model_validator(mode="after")
    def identities_components_and_contracts_must_match(self) -> Self:
        if tuple(component.role for component in self.components) != (
            "preprocessor",
            "classifier",
        ):
            raise ValueError("artifact components must be preprocessor then classifier")
        if (
            self.predictors.predictor_schema
            != self.provenance.training_manifest.predictor_schema
        ):
            raise ValueError(
                "artifact predictor schema does not match training provenance"
            )
        expected_model_id = deterministic_model_id(
            self.model, self.prediction, self.predictors, self.provenance
        )
        if self.model_id != expected_model_id:
            raise ValueError("model ID does not match its deterministic identity")
        for component in self.components:
            if component.component_id != deterministic_component_id(
                self.model_id, component
            ):
                raise ValueError(
                    "component ID does not match its deterministic identity"
                )
        if self.artifact_id != deterministic_artifact_id(
            self.model_id, self.components
        ):
            raise ValueError("artifact ID does not match its deterministic identity")
        if self.manifest_id != deterministic_manifest_id(self):
            raise ValueError("manifest ID does not match its deterministic identity")
        return self


@dataclass(frozen=True, slots=True)
class ModelArtifactPaths:
    directory: Path
    manifest: Path
    preprocessor: Path
    classifier: Path


def canonical_json_bytes(model: BaseModel | dict[str, object]) -> bytes:
    """Return the one canonical persisted JSON representation."""

    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _identity_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _uuid_for(kind: str, payload: dict[str, object]) -> UUID:
    digest = sha256_bytes(_identity_bytes(payload))
    return uuid5(NAMESPACE_URL, f"{MODEL_ARTIFACT_NAMESPACE}:{kind}:{digest}")


def deterministic_model_id(
    model: ModelSpecification,
    prediction: PredictionContract,
    predictors: PredictorCompatibility,
    provenance: ModelArtifactProvenance,
) -> UUID:
    return _uuid_for(
        "model",
        {
            "model": model.model_dump(mode="json"),
            "prediction": prediction.model_dump(mode="json"),
            "predictors": predictors.model_dump(mode="json"),
            "development_season_ids": provenance.development_season_ids,
            "training_dataset_id": provenance.training_manifest.dataset_id,
            "training_sha256": provenance.training_manifest.training_sha256,
            "training_manifest_sha256": provenance.training_manifest_sha256,
            "assessment_manifest_sha256": provenance.assessment_manifest_sha256,
            "untouched_test_freeze_manifest_sha256": (
                provenance.untouched_test_freeze_manifest_sha256
            ),
        },
    )


def deterministic_selected_model_id(provenance: ModelArtifactProvenance) -> UUID:
    """Return the model ID before component bytes have been serialized."""

    model = ModelSpecification(
        classifier=CatBoostClassifierMetadata(
            configuration=CatBoostParameters(
                id=SELECTED_CONFIGURATION_ID,
                iterations=200,
                depth=6,
                learning_rate=0.05,
                l2_leaf_reg=10.0,
            )
        )
    )
    return deterministic_model_id(
        model,
        PredictionContract(),
        PredictorCompatibility(
            predictor_schema=provenance.training_manifest.predictor_schema
        ),
        provenance,
    )


def deterministic_component_id(model_id: UUID, component: ArtifactComponent) -> UUID:
    return _uuid_for(
        "component",
        {
            "model_id": str(model_id),
            **component.model_dump(mode="json", exclude={"component_id"}),
        },
    )


def deterministic_artifact_id(
    model_id: UUID, components: tuple[ArtifactComponent, ArtifactComponent]
) -> UUID:
    return _uuid_for(
        "artifact",
        {
            "layout_version": MODEL_ARTIFACT_LAYOUT_VERSION,
            "model_id": str(model_id),
            "component_ids": tuple(
                str(component.component_id) for component in components
            ),
        },
    )


def deterministic_manifest_id(manifest: ModelArtifactManifest) -> UUID:
    return _uuid_for(
        "manifest",
        manifest.model_dump(mode="json", exclude={"manifest_id"}),
    )


def _component(
    model_id: UUID,
    *,
    role: Literal["preprocessor", "classifier"],
    integrity: ComponentIntegrity,
) -> ArtifactComponent:
    if role == "preprocessor":
        path = PREPROCESSOR_COMPONENT_PATH
        format_id: Literal[
            "pl-platform-ordered-numeric-preprocessor-json", "catboost-json"
        ] = "pl-platform-ordered-numeric-preprocessor-json"
    else:
        path = CLASSIFIER_COMPONENT_PATH
        format_id = "catboost-json"
    provisional = ArtifactComponent(
        component_id=UUID(int=0),
        role=role,
        relative_path=path,
        format_id=format_id,
        integrity=integrity,
    )
    return provisional.model_copy(
        update={"component_id": deterministic_component_id(model_id, provisional)}
    )


def build_model_artifact_manifest(
    provenance: ModelArtifactProvenance,
    *,
    preprocessor_integrity: ComponentIntegrity,
    classifier_integrity: ComponentIntegrity,
) -> ModelArtifactManifest:
    """Build identities around supplied bytes without serializing a model."""

    model = ModelSpecification(
        classifier=CatBoostClassifierMetadata(
            configuration=CatBoostParameters(
                id=SELECTED_CONFIGURATION_ID,
                iterations=200,
                depth=6,
                learning_rate=0.05,
                l2_leaf_reg=10.0,
            )
        )
    )
    prediction = PredictionContract()
    predictors = PredictorCompatibility(
        predictor_schema=provenance.training_manifest.predictor_schema
    )
    runtime = ArtifactRuntimeRequirements()
    model_id = deterministic_model_id(model, prediction, predictors, provenance)
    components = (
        _component(model_id, role="preprocessor", integrity=preprocessor_integrity),
        _component(model_id, role="classifier", integrity=classifier_integrity),
    )
    artifact_id = deterministic_artifact_id(model_id, components)
    fields: dict[str, object] = {
        "manifest_schema_id": MODEL_ARTIFACT_SCHEMA_ID,
        "manifest_schema_version": MODEL_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "layout_version": MODEL_ARTIFACT_LAYOUT_VERSION,
        "model_id": model_id,
        "artifact_id": artifact_id,
        "model": model,
        "prediction": prediction,
        "predictors": predictors,
        "runtime": runtime,
        "provenance": provenance,
        "components": components,
    }
    identity_fields: dict[str, object] = {
        "manifest_schema_id": MODEL_ARTIFACT_SCHEMA_ID,
        "manifest_schema_version": MODEL_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "layout_version": MODEL_ARTIFACT_LAYOUT_VERSION,
        "model_id": str(model_id),
        "artifact_id": str(artifact_id),
        "model": model.model_dump(mode="json"),
        "prediction": prediction.model_dump(mode="json"),
        "predictors": predictors.model_dump(mode="json"),
        "runtime": runtime.model_dump(mode="json"),
        "provenance": provenance.model_dump(mode="json"),
        "components": tuple(
            component.model_dump(mode="json") for component in components
        ),
    }
    fields["manifest_id"] = _uuid_for("manifest", identity_fields)
    return ModelArtifactManifest.model_validate(fields)


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or str(path) != value
    ):
        raise ValueError("artifact component path must be canonical and relative")


def model_artifact_paths(
    artifact_root: Path, manifest: ModelArtifactManifest
) -> ModelArtifactPaths:
    directory = (
        artifact_root
        / "models"
        / f"v{manifest.layout_version}"
        / str(manifest.model_id)
        / str(manifest.artifact_id)
    )
    return ModelArtifactPaths(
        directory=directory,
        manifest=directory / MANIFEST_FILENAME,
        preprocessor=directory / Path(PREPROCESSOR_COMPONENT_PATH),
        classifier=directory / Path(CLASSIFIER_COMPONENT_PATH),
    )


def current_runtime_environment() -> ArtifactRuntimeEnvironment:
    return ArtifactRuntimeEnvironment(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        pointer_width_bits=struct.calcsize("P") * 8,
        catboost_version=version("catboost"),
        numpy_version=version("numpy"),
        pydantic_version=version("pydantic"),
        tzdata_version=version("tzdata"),
    )


def assert_runtime_compatible(
    manifest: ModelArtifactManifest,
    environment: ArtifactRuntimeEnvironment | None = None,
) -> None:
    observed = environment or current_runtime_environment()
    required = manifest.runtime
    comparisons = {
        "python implementation": (
            observed.python_implementation,
            required.python_implementation,
        ),
        "Python version": (observed.python_version, required.python_version),
        "pointer width": (observed.pointer_width_bits, required.pointer_width_bits),
        "CatBoost version": (observed.catboost_version, required.catboost_version),
        "NumPy version": (observed.numpy_version, required.numpy_version),
        "Pydantic version": (observed.pydantic_version, required.pydantic_version),
        "tzdata version": (observed.tzdata_version, required.tzdata_version),
    }
    mismatches = [
        f"{name}: found {actual!r}, require {expected!r}"
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    ]
    if mismatches:
        raise ModelArtifactError(
            ArtifactFailureCode.RUNTIME_INCOMPATIBLE,
            "; ".join(mismatches),
        )


def load_model_artifact_manifest(
    path: Path,
    *,
    artifact_root: Path | None = None,
    check_runtime: bool = True,
) -> ModelArtifactManifest:
    """Load only a canonical manifest; component loading belongs to Step 4.2."""

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_INVALID,
            "manifest is missing or unreadable",
        ) from exc
    try:
        manifest = ModelArtifactManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_INVALID, "manifest contract validation failed"
        ) from exc
    if canonical_json_bytes(manifest) != payload:
        raise ModelArtifactError(
            ArtifactFailureCode.MANIFEST_NON_CANONICAL,
            "manifest bytes are not canonical",
        )
    if (
        artifact_root is not None
        and path.resolve()
        != model_artifact_paths(artifact_root, manifest).manifest.resolve()
    ):
        raise ModelArtifactError(
            ArtifactFailureCode.PATH_INVALID,
            "manifest is not at its deterministic artifact path",
        )
    if check_runtime:
        assert_runtime_compatible(manifest)
    return manifest
