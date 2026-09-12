"""Materialize test freeze and deterministic CatBoost tuning artifacts."""

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

from pl_platform.domain.evaluation import (
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
)
from pl_platform.evaluation.catboost_model import (
    CATBOOST_CANDIDATES,
    CATBOOST_METHOD_VERSION,
    CATBOOST_RANDOM_SEED,
    CatBoostFitDiagnostics,
    CatBoostParameters,
)
from pl_platform.evaluation.catboost_tuning import (
    CatBoostCandidateResult,
    CatBoostTuningResult,
    tune_catboost_with_walk_forward,
)
from pl_platform.evaluation.test_freeze import (
    UntouchedTestFreeze,
    build_test_freeze,
    write_test_freeze,
)
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    EXCLUDED_SEASONS,
    walk_forward_windows,
)
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    load_training_dataset,
    materialize_training_dataset,
)

CATBOOST_TUNING_DATASET_SCHEMA_VERSION: Final = 1
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class CatBoostTuningDatasetError(ValueError):
    """CatBoost tuning artifacts violate chronology, identity or provenance."""


class CatBoostFitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    tree_count: PositiveInt
    predictor_count: PositiveInt
    training_row_count: PositiveInt


class CatBoostFoldReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    reference_season_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_season_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_row_count: PositiveInt
    fit: CatBoostFitReport
    metric: ProbabilisticMetricSummary

    @model_validator(mode="after")
    def fold_must_report_catboost(self) -> Self:
        if self.metric.method != "catboost":
            msg = "CatBoost fold metric must use the catboost method"
            raise ValueError(msg)
        if self.metric.prediction_count != self.evaluation_row_count:
            msg = "CatBoost fold metric count must match its evaluation rows"
            raise ValueError(msg)
        return self


class CatBoostCandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parameters: CatBoostParameters
    folds: tuple[CatBoostFoldReport, ...] = Field(min_length=5, max_length=5)
    aggregate_metric: ProbabilisticMetricSummary

    @model_validator(mode="after")
    def aggregate_must_cover_all_folds(self) -> Self:
        if self.aggregate_metric.method != "catboost":
            msg = "CatBoost aggregate metric must use the catboost method"
            raise ValueError(msg)
        if self.aggregate_metric.prediction_count != sum(
            fold.metric.prediction_count for fold in self.folds
        ):
            msg = "CatBoost aggregate metric does not cover every fold"
            raise ValueError(msg)
        if any(fold.fit.candidate_id != self.parameters.id for fold in self.folds):
            msg = "CatBoost fold fit does not match its candidate"
            raise ValueError(msg)
        return self


class CatBoostRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_version: Literal[1]
    library: Literal["catboost-1.2.10"]
    task_type: Literal["CPU"]
    thread_count: Literal[1]
    random_seed: Literal[20260912]
    bootstrap_type: Literal["No"]
    random_strength: Annotated[
        float,
        Field(strict=True, ge=0.0, le=0.0, allow_inf_nan=False),
    ]
    allow_writing_files: Literal[False]
    loss_function: Literal["MultiClass"]
    class_order: tuple[
        Literal["home_win"],
        Literal["draw"],
        Literal["away_win"],
    ]


class CatBoostTuningDatasetManifest(BaseModel):
    """Versioned development-only candidate comparison and selected result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: Literal["catboost-tuning-v1-2015-2016-to-2024-2025"]
    competition_id: Literal["eng-premier-league"]
    development_season_ids: tuple[str, ...]
    untouched_test_season_ids: tuple[str, ...]
    source_training_manifest_sha256: Sha256
    source_training_manifest: TrainingDatasetManifest
    test_freeze_manifest_sha256: Sha256
    test_freeze: UntouchedTestFreeze
    runtime: CatBoostRuntimeContract
    candidates: tuple[CatBoostCandidateReport, ...] = Field(min_length=3, max_length=3)
    selection_rule: Literal[
        "minimum_walk_forward_log_loss_then_brier_then_rps_then_candidate_id"
    ]
    selected_candidate_id: str = Field(min_length=1)
    selected_prediction_row_count: PositiveInt
    selected_predictions_sha256: Sha256
    selected_predictions_ordered_by: tuple[
        Literal["partition_id"],
        Literal["feature_cutoff_at"],
        Literal["kickoff_at"],
        Literal["training_example_id"],
    ]
    final_development_fit: CatBoostFitReport

    @model_validator(mode="after")
    def tuning_contract_must_be_complete_and_development_only(self) -> Self:
        if self.development_season_ids != DEVELOPMENT_SEASONS:
            msg = "CatBoost tuning has an unsupported development window"
            raise ValueError(msg)
        if self.untouched_test_season_ids != EXCLUDED_SEASONS:
            msg = "CatBoost tuning has an unsupported untouched test window"
            raise ValueError(msg)
        if (
            self.test_freeze.source_training_dataset_id
            != self.source_training_manifest.dataset_id
            or self.test_freeze.source_training_sha256
            != self.source_training_manifest.training_sha256
            or self.test_freeze.source_training_manifest_sha256
            != self.source_training_manifest_sha256
        ):
            msg = "test freeze does not match the embedded training lineage"
            raise ValueError(msg)
        source_rows_by_season = {
            source.season_id: source.feature_row_count
            for source in self.source_training_manifest.source_feature_datasets
        }
        expected_test_rows = sum(
            source_rows_by_season[season_id]
            for season_id in self.untouched_test_season_ids
        )
        if self.test_freeze.test_row_count != expected_test_rows:
            msg = "test freeze row count does not match the training provenance"
            raise ValueError(msg)
        expected_candidates = tuple(candidate.id for candidate in CATBOOST_CANDIDATES)
        actual_candidates = tuple(
            candidate.parameters.id for candidate in self.candidates
        )
        if actual_candidates != expected_candidates:
            msg = "CatBoost candidate set or order is unsupported"
            raise ValueError(msg)
        expected_windows = walk_forward_windows()
        predictor_count = len(
            self.source_training_manifest.predictor_schema.predictor_names
        )
        for candidate in self.candidates:
            for fold, expected_window in zip(
                candidate.folds,
                expected_windows,
                strict=True,
            ):
                if (
                    fold.id != expected_window.id
                    or fold.reference_season_ids != expected_window.reference_season_ids
                    or fold.evaluation_season_ids
                    != expected_window.evaluation_season_ids
                ):
                    msg = "CatBoost report contains an unsupported fold boundary"
                    raise ValueError(msg)
                expected_training_rows = sum(
                    source_rows_by_season[season_id]
                    for season_id in fold.reference_season_ids
                )
                expected_evaluation_rows = sum(
                    source_rows_by_season[season_id]
                    for season_id in fold.evaluation_season_ids
                )
                if (
                    fold.fit.tree_count != candidate.parameters.iterations
                    or fold.fit.predictor_count != predictor_count
                    or fold.fit.training_row_count != expected_training_rows
                    or fold.evaluation_row_count != expected_evaluation_rows
                ):
                    msg = "CatBoost fold diagnostics do not match verified inputs"
                    raise ValueError(msg)
        if self.selected_candidate_id not in actual_candidates:
            msg = "selected CatBoost candidate is not in the candidate set"
            raise ValueError(msg)
        selected = next(
            candidate
            for candidate in self.candidates
            if candidate.parameters.id == self.selected_candidate_id
        )
        expected_selected = min(
            self.candidates,
            key=lambda candidate: (
                candidate.aggregate_metric.mean_log_loss,
                candidate.aggregate_metric.mean_multiclass_brier_score,
                candidate.aggregate_metric.mean_ranked_probability_score,
                candidate.parameters.id,
            ),
        )
        if selected != expected_selected:
            msg = "selected CatBoost candidate does not satisfy the selection rule"
            raise ValueError(msg)
        if (
            self.selected_prediction_row_count
            != selected.aggregate_metric.prediction_count
        ):
            msg = "selected prediction count does not match selected candidate metrics"
            raise ValueError(msg)
        if self.final_development_fit.candidate_id != self.selected_candidate_id:
            msg = "final development fit does not use the selected candidate"
            raise ValueError(msg)
        expected_development_rows = sum(
            source_rows_by_season[season_id]
            for season_id in self.development_season_ids
        )
        if (
            self.final_development_fit.tree_count != selected.parameters.iterations
            or self.final_development_fit.predictor_count != predictor_count
            or self.final_development_fit.training_row_count
            != expected_development_rows
        ):
            msg = "final CatBoost fit diagnostics do not match verified inputs"
            raise ValueError(msg)
        training_payload = (
            json.dumps(
                self.source_training_manifest.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        if _sha256(training_payload) != self.source_training_manifest_sha256:
            msg = "embedded training manifest does not match its checksum"
            raise ValueError(msg)
        freeze_payload = (
            json.dumps(
                self.test_freeze.model_dump(mode="json"), indent=2, sort_keys=True
            )
            + "\n"
        ).encode()
        if _sha256(freeze_payload) != self.test_freeze_manifest_sha256:
            msg = "embedded test freeze does not match its checksum"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class CatBoostTuningMaterializationResult:
    predictions_path: Path
    manifest_path: Path
    test_freeze_manifest_path: Path
    selected_candidate_id: str
    selected_prediction_row_count: int
    selected_predictions_sha256: str
    manifest_sha256: str
    test_freeze_manifest_sha256: str
    status: Literal["written", "already_current"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _fit_report(diagnostics: CatBoostFitDiagnostics) -> CatBoostFitReport:
    return CatBoostFitReport(
        candidate_id=diagnostics.candidate_id,
        tree_count=diagnostics.tree_count,
        predictor_count=diagnostics.predictor_count,
        training_row_count=diagnostics.training_row_count,
    )


def _candidate_report(result: CatBoostCandidateResult) -> CatBoostCandidateReport:
    return CatBoostCandidateReport(
        parameters=result.parameters,
        folds=tuple(
            CatBoostFoldReport(
                id=fold.window.id,
                reference_season_ids=fold.window.reference_season_ids,
                evaluation_season_ids=fold.window.evaluation_season_ids,
                evaluation_row_count=len(fold.predictions),
                fit=_fit_report(fold.fit),
                metric=fold.metric,
            )
            for fold in result.folds
        ),
        aggregate_metric=result.aggregate_metric,
    )


def _stable_prediction_bytes(
    predictions: Sequence[ProbabilisticPrediction],
) -> bytes:
    ordered = sorted(
        predictions,
        key=lambda item: (
            item.partition_id,
            item.feature_cutoff_at,
            item.kickoff_at,
            item.source_training_example_id,
        ),
    )
    lines = (
        json.dumps(
            prediction.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for prediction in ordered
    )
    return ("\n".join(lines) + "\n").encode()


def _validate_selected_predictions(
    predictions: Sequence[ProbabilisticPrediction],
    manifest: CatBoostTuningDatasetManifest,
) -> None:
    if len(predictions) != manifest.selected_prediction_row_count:
        msg = "selected CatBoost prediction count does not match its manifest"
        raise CatBoostTuningDatasetError(msg)
    identities = tuple(prediction.id for prediction in predictions)
    if len(identities) != len(set(identities)):
        msg = "selected CatBoost prediction IDs must be unique"
        raise CatBoostTuningDatasetError(msg)
    fold_by_id = {window.id: window for window in walk_forward_windows()}
    for prediction in predictions:
        fold = fold_by_id.get(prediction.partition_id)
        if fold is None:
            msg = f"CatBoost prediction {prediction.id} references an unknown fold"
            raise CatBoostTuningDatasetError(msg)
        if (
            prediction.method != "catboost"
            or prediction.configuration_id != manifest.selected_candidate_id
            or prediction.source_training_dataset_id
            != manifest.source_training_manifest.dataset_id
            or prediction.source_training_sha256
            != manifest.source_training_manifest.training_sha256
        ):
            msg = f"CatBoost prediction {prediction.id} has inconsistent lineage"
            raise CatBoostTuningDatasetError(msg)
        if prediction.season_id not in fold.evaluation_season_ids:
            msg = f"CatBoost prediction {prediction.id} is outside its fold"
            raise CatBoostTuningDatasetError(msg)
        if prediction.season_id in manifest.untouched_test_season_ids:
            msg = "untouched test season cannot appear in CatBoost predictions"
            raise CatBoostTuningDatasetError(msg)


def write_catboost_tuning_dataset(
    tuning: CatBoostTuningResult,
    output_directory: Path,
    source_training_manifest: TrainingDatasetManifest,
    source_training_manifest_sha256: str,
    test_freeze: UntouchedTestFreeze,
    test_freeze_manifest_path: Path,
    test_freeze_manifest_sha256: str,
) -> CatBoostTuningMaterializationResult:
    """Publish selected fold predictions and the complete candidate report."""

    prediction_payload = _stable_prediction_bytes(tuning.selected_predictions)
    manifest = CatBoostTuningDatasetManifest(
        dataset_schema_version=CATBOOST_TUNING_DATASET_SCHEMA_VERSION,
        dataset_id="catboost-tuning-v1-2015-2016-to-2024-2025",
        competition_id="eng-premier-league",
        development_season_ids=DEVELOPMENT_SEASONS,
        untouched_test_season_ids=EXCLUDED_SEASONS,
        source_training_manifest_sha256=source_training_manifest_sha256,
        source_training_manifest=source_training_manifest,
        test_freeze_manifest_sha256=test_freeze_manifest_sha256,
        test_freeze=test_freeze,
        runtime=CatBoostRuntimeContract(
            method_version=CATBOOST_METHOD_VERSION,
            library="catboost-1.2.10",
            task_type="CPU",
            thread_count=1,
            random_seed=CATBOOST_RANDOM_SEED,
            bootstrap_type="No",
            random_strength=0.0,
            allow_writing_files=False,
            loss_function="MultiClass",
            class_order=("home_win", "draw", "away_win"),
        ),
        candidates=tuple(_candidate_report(result) for result in tuning.candidates),
        selection_rule=(
            "minimum_walk_forward_log_loss_then_brier_then_rps_then_candidate_id"
        ),
        selected_candidate_id=tuning.selected_candidate_id,
        selected_prediction_row_count=len(tuning.selected_predictions),
        selected_predictions_sha256=_sha256(prediction_payload),
        selected_predictions_ordered_by=(
            "partition_id",
            "feature_cutoff_at",
            "kickoff_at",
            "training_example_id",
        ),
        final_development_fit=_fit_report(tuning.final_development_fit),
    )
    _validate_selected_predictions(tuning.selected_predictions, manifest)
    manifest_payload = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()
    predictions_path = output_directory / "selected-predictions.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"
    is_current = (
        predictions_path.exists()
        and manifest_path.exists()
        and predictions_path.read_bytes() == prediction_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(predictions_path, prediction_payload)
        _atomic_write(manifest_path, manifest_payload)
    return CatBoostTuningMaterializationResult(
        predictions_path=predictions_path,
        manifest_path=manifest_path,
        test_freeze_manifest_path=test_freeze_manifest_path,
        selected_candidate_id=tuning.selected_candidate_id,
        selected_prediction_row_count=len(tuning.selected_predictions),
        selected_predictions_sha256=_sha256(prediction_payload),
        manifest_sha256=_sha256(manifest_payload),
        test_freeze_manifest_sha256=test_freeze_manifest_sha256,
        status="already_current" if is_current else "written",
    )


def load_catboost_tuning_dataset(
    predictions_path: Path,
    manifest_path: Path,
) -> tuple[tuple[ProbabilisticPrediction, ...], CatBoostTuningDatasetManifest]:
    """Load selected predictions after strict checksum and contract validation."""

    manifest = CatBoostTuningDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    payload = predictions_path.read_bytes()
    if _sha256(payload) != manifest.selected_predictions_sha256:
        msg = "selected CatBoost prediction checksum does not match its manifest"
        raise CatBoostTuningDatasetError(msg)
    predictions = tuple(
        ProbabilisticPrediction.model_validate_json(line)
        for line in payload.decode().splitlines()
    )
    if _stable_prediction_bytes(predictions) != payload:
        msg = "selected CatBoost predictions are not deterministically ordered"
        raise CatBoostTuningDatasetError(msg)
    _validate_selected_predictions(predictions, manifest)
    return predictions, manifest


def materialize_catboost_tuning(
    historical_manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> CatBoostTuningMaterializationResult:
    """Reverify sources, freeze the test season and tune on development folds."""

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
    training_manifest_sha256 = _sha256(training_result.manifest_path.read_bytes())
    freeze = build_test_freeze(
        examples,
        training_manifest,
        training_manifest_sha256,
    )
    freeze_result = write_test_freeze(
        freeze,
        data_root / "processed" / "evaluation" / "epl" / "test-2025-2026",
    )
    tuning = tune_catboost_with_walk_forward(
        examples,
        training_manifest.predictor_schema.predictor_names,
        source_training_dataset_id=training_manifest.dataset_id,
        source_training_sha256=training_manifest.training_sha256,
    )
    result = write_catboost_tuning_dataset(
        tuning,
        data_root
        / "processed"
        / "evaluation"
        / "epl"
        / "catboost-tuning-2015-2016_to_2024-2025",
        training_manifest,
        training_manifest_sha256,
        freeze,
        freeze_result.manifest_path,
        freeze_result.manifest_sha256,
    )
    return CatBoostTuningMaterializationResult(
        predictions_path=result.predictions_path,
        manifest_path=result.manifest_path,
        test_freeze_manifest_path=freeze_result.manifest_path,
        selected_candidate_id=result.selected_candidate_id,
        selected_prediction_row_count=result.selected_prediction_row_count,
        selected_predictions_sha256=result.selected_predictions_sha256,
        manifest_sha256=result.manifest_sha256,
        test_freeze_manifest_sha256=result.test_freeze_manifest_sha256,
        status=result.status,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze the test season and tune deterministic CatBoost."
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
        result = materialize_catboost_tuning(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    for field_name in (
        "predictions_path",
        "manifest_path",
        "test_freeze_manifest_path",
    ):
        serialized[field_name] = str(getattr(result, field_name))
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
