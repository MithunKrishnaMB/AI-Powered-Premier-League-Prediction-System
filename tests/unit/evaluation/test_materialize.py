"""Tests for deterministic probabilistic evaluation materialization."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pl_platform.evaluation.materialize as evaluation_module
from pl_platform.evaluation.logistic import LogisticRegressionParameters
from pl_platform.evaluation.materialize import (
    EvaluationDatasetError,
    EvaluationMaterializationResult,
    load_evaluation_dataset,
    main,
    materialize_model_evaluation,
    write_evaluation_dataset,
)
from pl_platform.evaluation.walk_forward import (
    CompleteEvaluationResult,
    evaluate_holdout_and_walk_forward,
)
from pl_platform.features.materialize import FeaturePredictorSchema
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    TrainingFeatureSource,
    TrainingInputChecksums,
    TrainingMaterializationResult,
    TrainingTargetSchema,
)
from tests.unit.evaluation.helpers import (
    PREDICTOR_NAMES,
    SOURCE_TRAINING_SHA256,
    complete_corpus,
)

FAST_PARAMETERS = LogisticRegressionParameters(
    maximum_iterations=100,
    convergence_tolerance=1e-3,
    convergence_patience=2,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _training_manifest() -> TrainingDatasetManifest:
    names_payload = json.dumps(
        PREDICTOR_NAMES,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    seasons = tuple(f"{year:04d}-{year + 1:04d}" for year in range(2015, 2026))
    sources = tuple(
        TrainingFeatureSource(
            dataset_id=f"features-{season}",
            season_id=season,
            feature_row_count=3,
            features_sha256=f"{index:x}".rjust(64, "0"),
            feature_manifest_sha256=f"{index + 20:x}".rjust(64, "0"),
            canonical_dataset_id=f"canonical-{season}",
            canonical_fixtures_sha256=f"{index + 40:x}".rjust(64, "0"),
            historical_context_sha256=f"{index + 60:x}".rjust(64, "0"),
            raw_source_id="verified-source",
            raw_artifact_id=f"epl-{season}",
            raw_sha256=f"{index + 80:x}".rjust(64, "0"),
            raw_captured_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        for index, season in enumerate(seasons, start=1)
    )
    return TrainingDatasetManifest(
        dataset_schema_version=1,
        dataset_id="test-training-dataset",
        competition_id="eng-premier-league",
        season_ids=seasons,
        training_row_count=33,
        training_sha256=SOURCE_TRAINING_SHA256,
        training_row_schema_version=1,
        predictor_schema=FeaturePredictorSchema(
            id="epl-pre-match",
            version=2,
            predictor_count=3,
            predictor_names=PREDICTOR_NAMES,
            predictor_names_sha256=_sha256(names_payload),
        ),
        target_schema=TrainingTargetSchema(
            id="full-time-result-and-score",
            version=1,
            fields=("outcome", "home_goals", "away_goals"),
            outcome_values=("home_win", "draw", "away_win"),
        ),
        ordered_by=("kickoff_at", "training_example_id"),
        input_checksums=TrainingInputChecksums(
            historical_manifest_sha256="b" * 64,
            team_registry_sha256="c" * 64,
            season_registry_sha256="d" * 64,
        ),
        source_feature_datasets=sources,
    )


def _training_manifest_payload(manifest: TrainingDatasetManifest) -> bytes:
    return (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


def _complete_result() -> CompleteEvaluationResult:
    return evaluate_holdout_and_walk_forward(
        complete_corpus(),
        PREDICTOR_NAMES,
        source_training_dataset_id="test-training-dataset",
        source_training_sha256=SOURCE_TRAINING_SHA256,
        logistic_parameters=FAST_PARAMETERS,
    )


def test_writes_loads_and_reuses_deterministic_evaluation_bytes(tmp_path: Path) -> None:
    complete = _complete_result()
    output = tmp_path / "evaluation"
    source_manifest = _training_manifest()
    source_manifest_sha256 = _sha256(_training_manifest_payload(source_manifest))

    first = write_evaluation_dataset(
        complete.predictions,
        output,
        source_manifest,
        source_manifest_sha256,
        complete.holdout,
        complete.walk_forward_folds,
        complete.walk_forward_aggregate_metrics,
        complete.logistic_parameters,
    )
    second = write_evaluation_dataset(
        tuple(reversed(complete.predictions)),
        output,
        source_manifest,
        source_manifest_sha256,
        complete.holdout,
        complete.walk_forward_folds,
        complete.walk_forward_aggregate_metrics,
        complete.logistic_parameters,
    )
    predictions, manifest = load_evaluation_dataset(
        first.predictions_path,
        first.manifest_path,
    )

    assert first.status == "written"
    assert second.status == "already_current"
    assert len(predictions) == 63
    assert manifest.holdout.id == "step-3-1-holdout"
    assert manifest.source_training_manifest == source_manifest
    assert first.predictions_sha256 == _sha256(first.predictions_path.read_bytes())
    assert first.manifest_sha256 == _sha256(first.manifest_path.read_bytes())


def test_loader_rejects_checksum_and_order_corruption(tmp_path: Path) -> None:
    complete = _complete_result()
    source_manifest = _training_manifest()
    result = write_evaluation_dataset(
        complete.predictions,
        tmp_path,
        source_manifest,
        _sha256(_training_manifest_payload(source_manifest)),
        complete.holdout,
        complete.walk_forward_folds,
        complete.walk_forward_aggregate_metrics,
        complete.logistic_parameters,
    )
    original_payload = result.predictions_path.read_bytes()
    result.predictions_path.write_bytes(original_payload + b"\n")
    with pytest.raises(EvaluationDatasetError, match="checksum"):
        load_evaluation_dataset(result.predictions_path, result.manifest_path)

    lines = original_payload.decode().splitlines()
    reversed_payload = ("\n".join(reversed(lines)) + "\n").encode()
    result.predictions_path.write_bytes(reversed_payload)
    manifest_payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest_payload["predictions_sha256"] = _sha256(reversed_payload)
    result.manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError, match="deterministic order"):
        load_evaluation_dataset(result.predictions_path, result.manifest_path)


def test_rejects_empty_or_duplicate_predictions(tmp_path: Path) -> None:
    complete = _complete_result()
    source_manifest = _training_manifest()
    arguments = (
        tmp_path,
        source_manifest,
        _sha256(_training_manifest_payload(source_manifest)),
        complete.holdout,
        complete.walk_forward_folds,
        complete.walk_forward_aggregate_metrics,
        complete.logistic_parameters,
    )
    with pytest.raises(EvaluationDatasetError, match="non-empty"):
        write_evaluation_dataset((), *arguments)
    duplicate = (*complete.predictions[:-1], complete.predictions[0])
    with pytest.raises(EvaluationDatasetError, match="unique IDs"):
        write_evaluation_dataset(duplicate, *arguments)


def test_orchestrator_reverifies_training_before_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_manifest = _training_manifest()
    complete = _complete_result()
    training_manifest_path = tmp_path / "training-manifest.json"
    training_manifest_path.write_bytes(_training_manifest_payload(source_manifest))
    training_result = TrainingMaterializationResult(
        training_rows_path=tmp_path / "training.jsonl",
        manifest_path=training_manifest_path,
        training_row_count=33,
        training_sha256=SOURCE_TRAINING_SHA256,
        status="already_current",
    )
    calls: list[str] = []

    def reverify(*args: object) -> TrainingMaterializationResult:
        calls.append(str(args[0]))
        return training_result

    monkeypatch.setattr(evaluation_module, "materialize_training_dataset", reverify)
    monkeypatch.setattr(
        evaluation_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), source_manifest),
    )
    monkeypatch.setattr(
        evaluation_module,
        "evaluate_holdout_and_walk_forward",
        lambda *args, **kwargs: complete,
    )

    result = materialize_model_evaluation(
        tmp_path / "historical.json",
        tmp_path / "teams.json",
        tmp_path / "seasons.json",
        tmp_path,
    )

    assert calls == [str(tmp_path / "historical.json")]
    assert result.prediction_row_count == 63
    assert result.predictions_path.parent.name == "development-2015-2016_to_2024-2025"


def test_cli_reports_success_and_model_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = EvaluationMaterializationResult(
        predictions_path=tmp_path / "predictions.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        prediction_row_count=7980,
        predictions_sha256="a" * 64,
        manifest_sha256="b" * 64,
        status="written",
    )
    monkeypatch.setattr(
        evaluation_module,
        "materialize_model_evaluation",
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
    assert json.loads(capsys.readouterr().out)["prediction_row_count"] == 7980

    def fail(*args: object) -> EvaluationMaterializationResult:
        raise EvaluationDatasetError("invalid evaluation")

    monkeypatch.setattr(evaluation_module, "materialize_model_evaluation", fail)
    with pytest.raises(SystemExit):
        main(arguments)
