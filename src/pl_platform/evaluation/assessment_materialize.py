"""Materialize the deterministic Steps 3.9-3.10 development assessment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import ProbabilisticPrediction
from pl_platform.evaluation.advanced_materialize import (
    AdvancedEvaluationManifest,
    load_advanced_evaluation_dataset,
)
from pl_platform.evaluation.assessment import (
    ASSESSMENT_METHOD_VERSION,
    AcceptanceReport,
    GlobalModelExplanations,
    build_acceptance_report,
    build_global_explanations,
)
from pl_platform.evaluation.catboost_materialize import (
    CatBoostTuningDatasetManifest,
    load_catboost_tuning_dataset,
)
from pl_platform.evaluation.materialize import (
    EvaluationDatasetManifest,
    load_evaluation_dataset,
)
from pl_platform.evaluation.test_freeze import load_test_freeze
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    EXCLUDED_SEASONS,
    examples_for_seasons,
    walk_forward_windows,
)
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    load_training_dataset,
    materialize_training_dataset,
)

MODEL_ASSESSMENT_SCHEMA_VERSION: Final = 1
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ModelAssessmentDatasetError(ValueError):
    """Assessment artifacts violate checksum, coverage or lineage guarantees."""


class AssessmentSources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    training_manifest_sha256: Sha256
    base_evaluation_manifest_sha256: Sha256
    base_predictions_sha256: Sha256
    catboost_tuning_manifest_sha256: Sha256
    catboost_selected_predictions_sha256: Sha256
    advanced_evaluation_manifest_sha256: Sha256
    advanced_predictions_sha256: Sha256
    untouched_test_freeze_manifest_sha256: Sha256


class ModelAssessmentManifest(BaseModel):
    """Standalone, canonical development-only acceptance and explanation report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: Literal["model-assessment-v1-2015-2016-to-2024-2025"]
    competition_id: Literal["eng-premier-league"]
    development_season_ids: tuple[str, ...]
    untouched_test_season_ids: tuple[str, ...]
    method_version: Literal[1]
    source_training_manifest: TrainingDatasetManifest
    sources: AssessmentSources
    acceptance: AcceptanceReport
    explanations: GlobalModelExplanations

    @model_validator(mode="after")
    def population_and_lineage_must_match(self) -> Self:
        if self.development_season_ids != DEVELOPMENT_SEASONS:
            raise ValueError("assessment has an unsupported development window")
        if self.untouched_test_season_ids != EXCLUDED_SEASONS:
            raise ValueError("assessment has an unsupported untouched test window")
        training_payload = _stable_model_bytes(self.source_training_manifest)
        if _sha256(training_payload) != self.sources.training_manifest_sha256:
            raise ValueError("embedded training manifest does not match its checksum")
        source_counts = {
            source.season_id: source.feature_row_count
            for source in self.source_training_manifest.source_feature_datasets
        }
        expected_development_rows = sum(
            source_counts[season_id] for season_id in DEVELOPMENT_SEASONS
        )
        expected_evaluation_rows = sum(
            source_counts[season_id] for season_id in DEVELOPMENT_SEASONS[-5:]
        )
        if (
            self.explanations.development_training_row_count
            != expected_development_rows
            or self.acceptance.baseline_aggregate_metric.prediction_count
            != expected_evaluation_rows
        ):
            raise ValueError("assessment counts do not match verified training inputs")
        predictor_names = self.source_training_manifest.predictor_schema.predictor_names
        if {
            item.predictor_name for item in self.explanations.logistic_predictors
        } != set(predictor_names) or {
            item.predictor_name for item in self.explanations.catboost_predictors
        } != set(predictor_names):
            raise ValueError("explanations do not cover the verified predictor schema")
        importance_total = sum(
            item.normalized_prediction_values_change
            for item in self.explanations.catboost_predictors
        )
        if abs(importance_total - 1.0) > 1e-12:
            raise ValueError("CatBoost normalized importances must sum to one")
        team_ids = tuple(item.team_id for item in self.explanations.poisson_teams)
        if team_ids != tuple(sorted(set(team_ids), key=str)):
            raise ValueError("Poisson explanation team IDs must be unique and ordered")
        return self


@dataclass(frozen=True, slots=True)
class ModelAssessmentMaterializationResult:
    manifest_path: Path
    manifest_sha256: str
    champion_method: str
    accepted_methods: tuple[str, ...]
    status: Literal["written", "already_current"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_model_bytes(model: BaseModel) -> bytes:
    return (
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


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


def _validate_source_lineage(
    training: TrainingDatasetManifest,
    training_sha256: str,
    base: EvaluationDatasetManifest,
    catboost: CatBoostTuningDatasetManifest,
    advanced: AdvancedEvaluationManifest,
) -> None:
    if any(
        manifest.source_training_manifest != training
        or manifest.source_training_manifest_sha256 != training_sha256
        for manifest in (base, catboost, advanced)
    ):
        raise ModelAssessmentDatasetError(
            "evaluation artifacts do not match current verified training data"
        )


def _validate_comparable_prediction_populations(
    base_predictions: Sequence[ProbabilisticPrediction],
    catboost_predictions: Sequence[ProbabilisticPrediction],
    advanced_predictions: Sequence[ProbabilisticPrediction],
) -> None:
    fold_ids = {fold.id for fold in walk_forward_windows()}

    def population(
        predictions: Sequence[ProbabilisticPrediction], method: str
    ) -> set[tuple[str, object]]:
        return {
            (prediction.partition_id, prediction.source_training_example_id)
            for prediction in predictions
            if prediction.method == method and prediction.partition_id in fold_ids
        }

    baseline = population(base_predictions, "naive")
    populations = {
        "elo": population(base_predictions, "elo"),
        "multinomial_logistic": population(base_predictions, "multinomial_logistic"),
        "catboost": population(catboost_predictions, "catboost"),
        "poisson": population(advanced_predictions, "poisson"),
        "dixon_coles": population(advanced_predictions, "dixon_coles"),
    }
    if not baseline or any(candidate != baseline for candidate in populations.values()):
        raise ModelAssessmentDatasetError(
            "candidate prediction populations do not match the naive fold identities"
        )


def write_model_assessment(
    output_directory: Path,
    training_manifest: TrainingDatasetManifest,
    sources: AssessmentSources,
    acceptance: AcceptanceReport,
    explanations: GlobalModelExplanations,
) -> ModelAssessmentMaterializationResult:
    """Atomically publish canonical assessment bytes."""

    manifest = ModelAssessmentManifest(
        dataset_schema_version=MODEL_ASSESSMENT_SCHEMA_VERSION,
        dataset_id="model-assessment-v1-2015-2016-to-2024-2025",
        competition_id="eng-premier-league",
        development_season_ids=DEVELOPMENT_SEASONS,
        untouched_test_season_ids=EXCLUDED_SEASONS,
        method_version=ASSESSMENT_METHOD_VERSION,
        source_training_manifest=training_manifest,
        sources=sources,
        acceptance=acceptance,
        explanations=explanations,
    )
    payload = _stable_model_bytes(manifest)
    path = output_directory / "assessment-manifest.json"
    is_current = path.exists() and path.read_bytes() == payload
    if not is_current:
        _atomic_write(path, payload)
    return ModelAssessmentMaterializationResult(
        manifest_path=path,
        manifest_sha256=_sha256(payload),
        champion_method=acceptance.champion_method,
        accepted_methods=acceptance.accepted_methods,
        status="already_current" if is_current else "written",
    )


def load_model_assessment(path: Path) -> ModelAssessmentManifest:
    """Load an assessment only when its bytes and embedded lineage are canonical."""

    payload = path.read_bytes()
    manifest = ModelAssessmentManifest.model_validate_json(payload)
    if _stable_model_bytes(manifest) != payload:
        raise ModelAssessmentDatasetError(
            "model assessment manifest bytes are not deterministic"
        )
    return manifest


def materialize_model_assessment(
    historical_manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> ModelAssessmentMaterializationResult:
    """Reverify raw data, sealed test lineage and all development evaluations."""

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
    training_sha256 = _sha256(training_result.manifest_path.read_bytes())
    evaluation_root = data_root / "processed" / "evaluation" / "epl"
    base_directory = evaluation_root / "development-2015-2016_to_2024-2025"
    base_predictions_path = base_directory / "predictions.jsonl"
    base_manifest_path = base_directory / "dataset-manifest.json"
    base_predictions, base = load_evaluation_dataset(
        base_predictions_path, base_manifest_path
    )
    catboost_directory = evaluation_root / "catboost-tuning-2015-2016_to_2024-2025"
    catboost_predictions_path = catboost_directory / "selected-predictions.jsonl"
    catboost_manifest_path = catboost_directory / "dataset-manifest.json"
    catboost_predictions, catboost = load_catboost_tuning_dataset(
        catboost_predictions_path, catboost_manifest_path
    )
    advanced_directory = evaluation_root / "advanced-development-2015-2016_to_2024-2025"
    advanced_predictions_path = advanced_directory / "predictions.jsonl"
    advanced_manifest_path = advanced_directory / "dataset-manifest.json"
    advanced_predictions, advanced = load_advanced_evaluation_dataset(
        advanced_predictions_path, advanced_manifest_path
    )
    _validate_source_lineage(
        training_manifest,
        training_sha256,
        base,
        catboost,
        advanced,
    )
    _validate_comparable_prediction_populations(
        base_predictions,
        catboost_predictions,
        advanced_predictions,
    )
    freeze_path = evaluation_root / "test-2025-2026" / "freeze-manifest.json"
    freeze = load_test_freeze(freeze_path)
    freeze_sha256 = _sha256(freeze_path.read_bytes())
    if (
        freeze != catboost.test_freeze
        or freeze_sha256 != catboost.test_freeze_manifest_sha256
        or freeze_sha256 != advanced.source_catboost_tuning.test_freeze_manifest_sha256
    ):
        raise ModelAssessmentDatasetError(
            "untouched test freeze does not match evaluation lineage"
        )
    catboost_manifest_sha256 = _sha256(catboost_manifest_path.read_bytes())
    if (
        advanced.source_catboost_tuning.manifest_sha256 != catboost_manifest_sha256
        or advanced.source_catboost_tuning.selected_predictions_sha256
        != catboost.selected_predictions_sha256
    ):
        raise ModelAssessmentDatasetError(
            "advanced evaluation does not match CatBoost tuning lineage"
        )
    acceptance = build_acceptance_report(base, catboost, advanced)
    development_examples = examples_for_seasons(examples, DEVELOPMENT_SEASONS)
    explanations = build_global_explanations(
        development_examples,
        training_manifest.predictor_schema.predictor_names,
        base,
        catboost,
        advanced,
    )
    sources = AssessmentSources(
        training_manifest_sha256=training_sha256,
        base_evaluation_manifest_sha256=_sha256(base_manifest_path.read_bytes()),
        base_predictions_sha256=base.predictions_sha256,
        catboost_tuning_manifest_sha256=catboost_manifest_sha256,
        catboost_selected_predictions_sha256=catboost.selected_predictions_sha256,
        advanced_evaluation_manifest_sha256=_sha256(
            advanced_manifest_path.read_bytes()
        ),
        advanced_predictions_sha256=advanced.predictions_sha256,
        untouched_test_freeze_manifest_sha256=freeze_sha256,
    )
    return write_model_assessment(
        evaluation_root / "model-assessment-2015-2016_to_2024-2025",
        training_manifest,
        sources,
        acceptance,
        explanations,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply frozen development gates and explain fitted models."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--seasons", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = materialize_model_assessment(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    serialized["manifest_path"] = str(result.manifest_path)
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
