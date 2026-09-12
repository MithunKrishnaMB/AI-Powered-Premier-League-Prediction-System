"""Materialize deterministic holdout and walk-forward model evaluation."""

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

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    OutcomeCounts,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
    ProbabilisticPrediction,
)
from pl_platform.evaluation.logistic import (
    LOGISTIC_METHOD_VERSION,
    LOGISTIC_PREPROCESSOR_VERSION,
    LogisticFitDiagnostics,
    LogisticRegressionParameters,
)
from pl_platform.evaluation.walk_forward import (
    DEVELOPMENT_SEASONS,
    EXCLUDED_SEASONS,
    EvaluationPartitionResult,
    evaluate_holdout_and_walk_forward,
)
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    load_training_dataset,
    materialize_training_dataset,
)

EVALUATION_DATASET_SCHEMA_VERSION: Final = 1
EvaluationMaterializationStatus = Literal["written", "already_current"]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvaluationDatasetError(ValueError):
    """Evaluation artifacts violate checksum, schema or lineage guarantees."""


class LogisticFitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    iterations: PositiveInt
    converged: bool
    final_objective: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    predictor_count: PositiveInt
    training_row_count: PositiveInt


class EvaluationPartitionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    reference_season_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_season_ids: tuple[str, ...] = Field(min_length=1)
    excluded_season_ids: tuple[str, ...]
    reference_row_count: PositiveInt
    evaluation_row_count: PositiveInt
    naive_reference_counts: OutcomeCounts
    naive_prior: OutcomeProbabilities
    logistic_fit: LogisticFitReport
    metrics: tuple[ProbabilisticMetricSummary, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def methods_and_counts_must_match(self) -> Self:
        methods = tuple(metric.method for metric in self.metrics)
        if methods != ("naive", "elo", "multinomial_logistic"):
            msg = "partition metrics must use the supported deterministic order"
            raise ValueError(msg)
        if any(
            metric.prediction_count != self.evaluation_row_count
            for metric in self.metrics
        ):
            msg = "partition metric counts must match evaluation rows"
            raise ValueError(msg)
        if self.naive_reference_counts.total != self.reference_row_count:
            msg = "naive reference counts must match reference rows"
            raise ValueError(msg)
        return self


class BenchmarkProcessingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    naive_method: Literal["reference_outcome_frequency"]
    elo_method: Literal["fixed_draw_relative_non_draw_share"]
    elo_home_signal: Literal["home_elo_expected_score"]
    elo_away_signal: Literal["away_elo_expected_score"]
    elo_draw_source: Literal["reference_naive_draw_frequency"]


class MetricProcessingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    outcome_order: tuple[
        Literal["home_win"],
        Literal["draw"],
        Literal["away_win"],
    ]
    log_loss: Literal["mean_natural_log_multiclass"]
    brier_score: Literal["mean_sum_three_class_squared_error"]
    ranked_probability_score: Literal["mean_two_threshold_normalized"]


class EvaluationDatasetManifest(BaseModel):
    """Complete deterministic lineage and metric report for Steps 3.1-3.3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: str = Field(min_length=1)
    competition_id: Literal["eng-premier-league"]
    development_season_ids: tuple[str, ...]
    excluded_season_ids: tuple[str, ...]
    prediction_row_schema_version: Literal[1]
    prediction_row_count: PositiveInt
    predictions_sha256: Sha256
    ordered_by: tuple[
        Literal["partition_id"],
        Literal["feature_cutoff_at"],
        Literal["kickoff_at"],
        Literal["training_example_id"],
        Literal["method"],
    ]
    source_training_manifest_sha256: Sha256
    source_training_manifest: TrainingDatasetManifest
    benchmark_contract: BenchmarkProcessingContract
    metric_contract: MetricProcessingContract
    logistic_method_version: Literal[1]
    logistic_preprocessor_version: Literal[1]
    logistic_parameters: LogisticRegressionParameters
    numerical_runtime: Literal["numpy-2.5.3-float64"]
    holdout: EvaluationPartitionReport
    walk_forward_folds: tuple[EvaluationPartitionReport, ...] = Field(
        min_length=5,
        max_length=5,
    )
    walk_forward_aggregate_metrics: tuple[ProbabilisticMetricSummary, ...] = Field(
        min_length=3,
        max_length=3,
    )

    @model_validator(mode="after")
    def evaluation_plan_and_counts_must_be_consistent(self) -> Self:
        if self.development_season_ids != DEVELOPMENT_SEASONS:
            msg = "evaluation manifest has an unsupported development window"
            raise ValueError(msg)
        if self.excluded_season_ids != EXCLUDED_SEASONS:
            msg = "evaluation manifest has an unsupported excluded window"
            raise ValueError(msg)
        expected_predictions = 3 * (
            self.holdout.evaluation_row_count
            + sum(fold.evaluation_row_count for fold in self.walk_forward_folds)
        )
        if self.prediction_row_count != expected_predictions:
            msg = "prediction count does not match holdout and fold populations"
            raise ValueError(msg)
        aggregate_methods = tuple(
            metric.method for metric in self.walk_forward_aggregate_metrics
        )
        if aggregate_methods != ("naive", "elo", "multinomial_logistic"):
            msg = "walk-forward metrics must use the supported deterministic order"
            raise ValueError(msg)
        aggregate_count = sum(
            fold.evaluation_row_count for fold in self.walk_forward_folds
        )
        if any(
            metric.prediction_count != aggregate_count
            for metric in self.walk_forward_aggregate_metrics
        ):
            msg = "aggregate metrics do not cover every walk-forward prediction"
            raise ValueError(msg)
        source_manifest_payload = (
            json.dumps(
                self.source_training_manifest.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        if (
            hashlib.sha256(source_manifest_payload).hexdigest()
            != self.source_training_manifest_sha256
        ):
            msg = "embedded training manifest does not match its checksum"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class EvaluationMaterializationResult:
    predictions_path: Path
    manifest_path: Path
    prediction_row_count: int
    predictions_sha256: str
    manifest_sha256: str
    status: EvaluationMaterializationStatus


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
            item.method,
        ),
    )
    lines = (
        json.dumps(
            prediction.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for prediction in ordered
    )
    return ("\n".join(lines) + "\n").encode()


def _fit_report(diagnostics: LogisticFitDiagnostics) -> LogisticFitReport:
    return LogisticFitReport(
        iterations=diagnostics.iterations,
        converged=diagnostics.converged,
        final_objective=diagnostics.final_objective,
        predictor_count=diagnostics.predictor_count,
        training_row_count=diagnostics.training_row_count,
    )


def _partition_report(
    result: EvaluationPartitionResult,
) -> EvaluationPartitionReport:
    return EvaluationPartitionReport(
        id=result.window.id,
        reference_season_ids=result.window.reference_season_ids,
        evaluation_season_ids=result.window.evaluation_season_ids,
        excluded_season_ids=result.window.excluded_season_ids,
        reference_row_count=result.reference_row_count,
        evaluation_row_count=result.evaluation_row_count,
        naive_reference_counts=result.naive_reference_counts,
        naive_prior=result.naive_prior,
        logistic_fit=_fit_report(result.logistic_fit),
        metrics=result.metrics,
    )


def _validate_predictions_against_manifest(
    predictions: Sequence[ProbabilisticPrediction],
    manifest: EvaluationDatasetManifest,
) -> None:
    source = manifest.source_training_manifest
    reports = (manifest.holdout, *manifest.walk_forward_folds)
    report_by_id = {report.id: report for report in reports}
    if len(predictions) != manifest.prediction_row_count:
        msg = "evaluation prediction count does not match its manifest"
        raise EvaluationDatasetError(msg)
    for prediction in predictions:
        if (
            prediction.source_training_dataset_id != source.dataset_id
            or prediction.source_training_sha256 != source.training_sha256
        ):
            msg = f"prediction {prediction.id} has inconsistent training lineage"
            raise EvaluationDatasetError(msg)
        report = report_by_id.get(prediction.partition_id)
        if report is None:
            msg = f"prediction {prediction.id} references an unknown partition"
            raise EvaluationDatasetError(msg)
        if prediction.season_id not in report.evaluation_season_ids:
            msg = f"prediction {prediction.id} is outside its evaluation seasons"
            raise EvaluationDatasetError(msg)

    for report in reports:
        partition = tuple(
            prediction
            for prediction in predictions
            if prediction.partition_id == report.id
        )
        identities_by_method: list[set[object]] = []
        for method in ("naive", "elo", "multinomial_logistic"):
            method_predictions = tuple(
                prediction for prediction in partition if prediction.method == method
            )
            identities = {
                prediction.source_training_example_id
                for prediction in method_predictions
            }
            if (
                len(method_predictions) != report.evaluation_row_count
                or len(identities) != report.evaluation_row_count
            ):
                msg = f"partition {report.id!r} has an incomplete method population"
                raise EvaluationDatasetError(msg)
            identities_by_method.append(set(identities))
        if any(
            identities != identities_by_method[0]
            for identities in identities_by_method[1:]
        ):
            msg = f"partition {report.id!r} methods evaluate different examples"
            raise EvaluationDatasetError(msg)


def write_evaluation_dataset(
    predictions: Sequence[ProbabilisticPrediction],
    output_directory: Path,
    source_training_manifest: TrainingDatasetManifest,
    source_training_manifest_sha256: str,
    holdout: EvaluationPartitionResult,
    walk_forward_folds: tuple[EvaluationPartitionResult, ...],
    walk_forward_aggregate_metrics: tuple[ProbabilisticMetricSummary, ...],
    logistic_parameters: LogisticRegressionParameters,
) -> EvaluationMaterializationResult:
    """Validate and atomically publish deterministic prediction and report bytes."""

    identities = tuple(prediction.id for prediction in predictions)
    if not predictions or len(identities) != len(set(identities)):
        msg = "evaluation predictions must be non-empty with unique IDs"
        raise EvaluationDatasetError(msg)
    predictions_payload = _stable_prediction_bytes(predictions)
    manifest = EvaluationDatasetManifest(
        dataset_schema_version=EVALUATION_DATASET_SCHEMA_VERSION,
        dataset_id="probabilistic-development-evaluation-v1-2015-2016-to-2024-2025",
        competition_id="eng-premier-league",
        development_season_ids=DEVELOPMENT_SEASONS,
        excluded_season_ids=EXCLUDED_SEASONS,
        prediction_row_schema_version=EVALUATION_SCHEMA_VERSION,
        prediction_row_count=len(predictions),
        predictions_sha256=_sha256(predictions_payload),
        ordered_by=(
            "partition_id",
            "feature_cutoff_at",
            "kickoff_at",
            "training_example_id",
            "method",
        ),
        source_training_manifest_sha256=source_training_manifest_sha256,
        source_training_manifest=source_training_manifest,
        benchmark_contract=BenchmarkProcessingContract(
            version=1,
            naive_method="reference_outcome_frequency",
            elo_method="fixed_draw_relative_non_draw_share",
            elo_home_signal="home_elo_expected_score",
            elo_away_signal="away_elo_expected_score",
            elo_draw_source="reference_naive_draw_frequency",
        ),
        metric_contract=MetricProcessingContract(
            version=1,
            outcome_order=("home_win", "draw", "away_win"),
            log_loss="mean_natural_log_multiclass",
            brier_score="mean_sum_three_class_squared_error",
            ranked_probability_score="mean_two_threshold_normalized",
        ),
        logistic_method_version=LOGISTIC_METHOD_VERSION,
        logistic_preprocessor_version=LOGISTIC_PREPROCESSOR_VERSION,
        logistic_parameters=logistic_parameters,
        numerical_runtime="numpy-2.5.3-float64",
        holdout=_partition_report(holdout),
        walk_forward_folds=tuple(
            _partition_report(fold) for fold in walk_forward_folds
        ),
        walk_forward_aggregate_metrics=walk_forward_aggregate_metrics,
    )
    _validate_predictions_against_manifest(predictions, manifest)
    manifest_payload = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()
    predictions_path = output_directory / "predictions.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"
    is_current = (
        predictions_path.exists()
        and manifest_path.exists()
        and predictions_path.read_bytes() == predictions_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(predictions_path, predictions_payload)
        _atomic_write(manifest_path, manifest_payload)
    return EvaluationMaterializationResult(
        predictions_path=predictions_path,
        manifest_path=manifest_path,
        prediction_row_count=len(predictions),
        predictions_sha256=_sha256(predictions_payload),
        manifest_sha256=_sha256(manifest_payload),
        status="already_current" if is_current else "written",
    )


def load_evaluation_dataset(
    predictions_path: Path,
    manifest_path: Path,
) -> tuple[tuple[ProbabilisticPrediction, ...], EvaluationDatasetManifest]:
    """Load predictions only after checksum, ordering and lineage validation."""

    manifest = EvaluationDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    payload = predictions_path.read_bytes()
    if _sha256(payload) != manifest.predictions_sha256:
        msg = "evaluation prediction checksum does not match its manifest"
        raise EvaluationDatasetError(msg)
    predictions = tuple(
        ProbabilisticPrediction.model_validate_json(line)
        for line in payload.decode().splitlines()
    )
    if len(predictions) != manifest.prediction_row_count:
        msg = "evaluation prediction count does not match its manifest"
        raise EvaluationDatasetError(msg)
    if _stable_prediction_bytes(predictions) != payload:
        msg = "evaluation predictions are not in deterministic order"
        raise EvaluationDatasetError(msg)
    identities = tuple(prediction.id for prediction in predictions)
    if len(identities) != len(set(identities)):
        msg = "evaluation prediction IDs must be unique"
        raise EvaluationDatasetError(msg)
    _validate_predictions_against_manifest(predictions, manifest)
    return predictions, manifest


def materialize_model_evaluation(
    historical_manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> EvaluationMaterializationResult:
    """Reverify all upstream data, then run Steps 3.1-3.3 evaluation."""

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
    complete = evaluate_holdout_and_walk_forward(
        examples,
        training_manifest.predictor_schema.predictor_names,
        source_training_dataset_id=training_manifest.dataset_id,
        source_training_sha256=training_manifest.training_sha256,
    )
    output_directory = (
        data_root
        / "processed"
        / "evaluation"
        / "epl"
        / "development-2015-2016_to_2024-2025"
    )
    return write_evaluation_dataset(
        complete.predictions,
        output_directory,
        training_manifest,
        _sha256(training_result.manifest_path.read_bytes()),
        complete.holdout,
        complete.walk_forward_folds,
        complete.walk_forward_aggregate_metrics,
        complete.logistic_parameters,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic Premier League probabilistic models."
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
        result = materialize_model_evaluation(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    serialized["predictions_path"] = str(result.predictions_path)
    serialized["manifest_path"] = str(result.manifest_path)
    print(json.dumps(serialized, sort_keys=True))
    return 0


if np.__version__ != "2.5.3":  # pragma: no cover - dependency pin enforces this.
    raise RuntimeError("evaluation requires the pinned NumPy 2.5.3 runtime")


if __name__ == "__main__":
    raise SystemExit(main())
