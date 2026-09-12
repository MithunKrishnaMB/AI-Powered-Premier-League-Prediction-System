"""Tests for Steps 3.6-3.8 artifact materialization and provenance."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import pl_platform.evaluation.advanced_materialize as materialize_module
from pl_platform.evaluation.advanced_materialize import (
    AdvancedEvaluationError,
    AdvancedEvaluationManifest,
    AdvancedEvaluationMaterializationResult,
    CatBoostTuningSource,
    load_advanced_evaluation_dataset,
    main,
    materialize_advanced_evaluation,
    write_advanced_evaluation_dataset,
)
from pl_platform.evaluation.calibration import (
    CalibrationEvaluationResult,
    evaluate_expanding_temperature_calibration,
)
from pl_platform.evaluation.score_models import (
    PoissonModelParameters,
    ScoreModelEvaluationResult,
    evaluate_score_models_walk_forward,
)
from pl_platform.training.materialize import TrainingMaterializationResult
from tests.unit.evaluation.helpers import (
    SOURCE_DATASET_ID,
    SOURCE_TRAINING_SHA256,
    catboost_predictions,
    complete_corpus,
    make_training_manifest,
    training_manifest_payload,
)

FAST_PARAMETERS = PoissonModelParameters(
    optimizer_iterations=40,
    dixon_coles_optimizer_iterations=24,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _evaluations() -> tuple[CalibrationEvaluationResult, ScoreModelEvaluationResult]:
    examples = complete_corpus()
    return (
        evaluate_expanding_temperature_calibration(catboost_predictions(), examples),
        evaluate_score_models_walk_forward(
            examples,
            source_training_dataset_id=SOURCE_DATASET_ID,
            source_training_sha256=SOURCE_TRAINING_SHA256,
            parameters=FAST_PARAMETERS,
        ),
    )


def _catboost_source() -> CatBoostTuningSource:
    return CatBoostTuningSource(
        dataset_id="catboost-test",
        manifest_sha256="e" * 64,
        selected_candidate_id="catboost-test",
        selected_prediction_row_count=15,
        selected_predictions_sha256="f" * 64,
        test_freeze_manifest_sha256="1" * 64,
    )


def _write(
    tmp_path: Path,
) -> tuple[
    AdvancedEvaluationMaterializationResult,
    CalibrationEvaluationResult,
    ScoreModelEvaluationResult,
]:
    calibration, score_models = _evaluations()
    manifest = make_training_manifest()
    result = write_advanced_evaluation_dataset(
        calibration,
        score_models,
        tmp_path / "advanced",
        manifest,
        _sha256(training_manifest_payload(manifest)),
        _catboost_source(),
    )
    return result, calibration, score_models


def test_writes_loads_and_reuses_deterministic_advanced_artifacts(
    tmp_path: Path,
) -> None:
    first, calibration, score_models = _write(tmp_path)
    manifest = make_training_manifest()
    reversed_calibration = replace(
        calibration,
        folds=tuple(
            replace(fold, predictions=tuple(reversed(fold.predictions)))
            for fold in calibration.folds
        ),
    )
    reversed_scores = replace(
        score_models,
        folds=tuple(
            replace(
                fold,
                poisson_predictions=tuple(reversed(fold.poisson_predictions)),
                dixon_coles_predictions=tuple(reversed(fold.dixon_coles_predictions)),
            )
            for fold in score_models.folds
        ),
    )
    second = write_advanced_evaluation_dataset(
        reversed_calibration,
        reversed_scores,
        tmp_path / "advanced",
        manifest,
        _sha256(training_manifest_payload(manifest)),
        _catboost_source(),
    )
    predictions, loaded_manifest = load_advanced_evaluation_dataset(
        first.predictions_path,
        first.manifest_path,
    )

    assert first.status == "written"
    assert second.status == "already_current"
    assert len(predictions) == 42
    assert loaded_manifest.calibration.final_fit.training_prediction_count == 15
    assert loaded_manifest.score_models.final_poisson_fit.training_row_count == 30


def test_loader_rejects_changed_or_noncanonical_bytes(tmp_path: Path) -> None:
    result, _, _ = _write(tmp_path)
    result.predictions_path.write_bytes(result.predictions_path.read_bytes() + b"\n")
    with pytest.raises(AdvancedEvaluationError, match="checksum"):
        load_advanced_evaluation_dataset(result.predictions_path, result.manifest_path)

    result, _, _ = _write(tmp_path / "second")
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AdvancedEvaluationError, match="manifest bytes"):
        load_advanced_evaluation_dataset(result.predictions_path, result.manifest_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("untouched", "untouched test window"),
        ("training_sha", "training manifest"),
        ("development", "development window"),
        ("prediction_count", "prediction count"),
        ("aggregate_count", "calibration aggregates"),
        ("catboost_count", "CatBoost source count"),
        ("score_fold", "unsupported fold"),
        ("score_count", "fold counts"),
        ("calibration_fold", "calibration fold"),
        ("final_count", "final development fit counts"),
        ("calibration_baseline_method", "baseline metric"),
        ("calibration_method", "calibrated metric"),
        ("calibration_count", "paired calibration metric counts"),
        ("poisson_bounds", "Poisson optimizer"),
        ("rho_bounds", "Dixon-Coles contract"),
        ("poisson_method", "Poisson fold metric"),
        ("dixon_coles_method", "Dixon-Coles fold metric"),
        ("score_metric_count", "score-model fold metric counts"),
        ("calibration_selection", "selection rule"),
        ("poisson_iterations", "fit iterations"),
        ("rho_fit", "fit rho"),
    ),
)
def test_manifest_rejects_boundary_and_count_drift(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    result, _, _ = _write(tmp_path)
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if mutation == "untouched":
        payload["untouched_test_season_ids"] = ["2024-2025"]
    elif mutation == "training_sha":
        payload["source_training_manifest_sha256"] = "0" * 64
    elif mutation == "development":
        payload["development_season_ids"] = payload["development_season_ids"][:-1]
    elif mutation == "prediction_count":
        payload["prediction_row_count"] += 1
    elif mutation == "aggregate_count":
        payload["calibration"]["aggregate_calibrated_metric"]["prediction_count"] += 1
        payload["calibration"]["aggregate_calibrated_metric"]["outcome_counts"][
            "home_win"
        ] += 1
    elif mutation == "catboost_count":
        payload["source_catboost_tuning"]["selected_prediction_row_count"] -= 1
    elif mutation == "score_fold":
        payload["score_models"]["folds"][0]["partition_id"] = "different"
    elif mutation == "score_count":
        payload["score_models"]["folds"][0]["poisson_fit"]["training_row_count"] += 1
    elif mutation == "calibration_fold":
        payload["calibration"]["folds"][0]["calibration_season_ids"] = ["2019-2020"]
    elif mutation == "final_count":
        payload["score_models"]["final_poisson_fit"]["training_row_count"] += 1
    elif mutation == "calibration_baseline_method":
        payload["calibration"]["folds"][0]["uncalibrated_metric"]["method"] = "poisson"
    elif mutation == "calibration_method":
        payload["calibration"]["folds"][0]["calibrated_metric"]["method"] = "catboost"
    elif mutation == "calibration_count":
        metric = payload["calibration"]["folds"][0]["calibrated_metric"]
        metric["prediction_count"] -= 1
        metric["outcome_counts"]["home_win"] -= 1
    elif mutation == "poisson_bounds":
        optimizer = payload["score_models"]["poisson_optimizer"]
        optimizer["minimum_expected_goals"] = optimizer["maximum_expected_goals"]
    elif mutation == "rho_bounds":
        contract = payload["score_models"]["dixon_coles_contract"]
        contract["rho_minimum"] = contract["rho_maximum"]
    elif mutation == "poisson_method":
        payload["score_models"]["folds"][0]["poisson_metric"]["method"] = "catboost"
    elif mutation == "dixon_coles_method":
        payload["score_models"]["folds"][0]["dixon_coles_metric"]["method"] = "catboost"
    elif mutation == "score_metric_count":
        metric = payload["score_models"]["folds"][0]["dixon_coles_metric"]
        metric["prediction_count"] -= 1
        metric["outcome_counts"]["home_win"] -= 1
    elif mutation == "calibration_selection":
        current = payload["calibration"]["selected_strategy"]
        payload["calibration"]["selected_strategy"] = (
            "identity" if current == "temperature_scaling" else "temperature_scaling"
        )
    elif mutation == "poisson_iterations":
        payload["score_models"]["folds"][0]["poisson_fit"]["optimizer_iterations"] += 1
    else:
        payload["score_models"]["dixon_coles_contract"]["rho_minimum"] = -0.01

    with pytest.raises(ValueError, match=message):
        AdvancedEvaluationManifest.model_validate(payload)


def test_writer_rejects_prediction_lineage_drift(tmp_path: Path) -> None:
    calibration, score_models = _evaluations()
    changed_prediction = (
        calibration.folds[0]
        .predictions[0]
        .model_copy(update={"source_training_dataset_id": "different"})
    )
    changed_fold = replace(
        calibration.folds[0],
        predictions=(changed_prediction, *calibration.folds[0].predictions[1:]),
    )
    changed_calibration = replace(
        calibration,
        folds=(changed_fold, *calibration.folds[1:]),
    )
    manifest = make_training_manifest()

    with pytest.raises(AdvancedEvaluationError, match="lineage"):
        write_advanced_evaluation_dataset(
            changed_calibration,
            score_models,
            tmp_path / "advanced",
            manifest,
            _sha256(training_manifest_payload(manifest)),
            _catboost_source(),
        )


def test_orchestrator_reverifies_training_and_checks_upstream_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration, score_models = _evaluations()
    source_manifest = make_training_manifest()
    training_manifest_path = tmp_path / "training-manifest.json"
    training_manifest_path.write_bytes(training_manifest_payload(source_manifest))
    training_result = TrainingMaterializationResult(
        training_rows_path=tmp_path / "training.jsonl",
        manifest_path=training_manifest_path,
        training_row_count=33,
        training_sha256=SOURCE_TRAINING_SHA256,
        status="already_current",
    )
    catboost_directory = (
        tmp_path
        / "processed"
        / "evaluation"
        / "epl"
        / "catboost-tuning-2015-2016_to_2024-2025"
    )
    catboost_directory.mkdir(parents=True)
    catboost_manifest_path = catboost_directory / "dataset-manifest.json"
    catboost_manifest_path.write_text("catboost", encoding="utf-8")
    freeze_path = (
        tmp_path
        / "processed"
        / "evaluation"
        / "epl"
        / "test-2025-2026"
        / "freeze-manifest.json"
    )
    freeze_path.parent.mkdir(parents=True)
    freeze_path.write_text("freeze", encoding="utf-8")
    freeze = object()
    catboost_manifest = SimpleNamespace(
        dataset_id="catboost-test",
        selected_candidate_id="catboost-test",
        selected_prediction_row_count=15,
        selected_predictions_sha256="f" * 64,
        test_freeze_manifest_sha256=_sha256(freeze_path.read_bytes()),
        source_training_manifest=source_manifest,
        source_training_manifest_sha256=_sha256(
            training_manifest_payload(source_manifest)
        ),
        test_freeze=freeze,
    )
    calls: list[str] = []

    def reverify(*args: object) -> TrainingMaterializationResult:
        calls.append(str(args[0]))
        return training_result

    monkeypatch.setattr(materialize_module, "materialize_training_dataset", reverify)
    monkeypatch.setattr(
        materialize_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), source_manifest),
    )
    monkeypatch.setattr(
        materialize_module,
        "load_catboost_tuning_dataset",
        lambda *args: (catboost_predictions(), catboost_manifest),
    )
    monkeypatch.setattr(materialize_module, "load_test_freeze", lambda *args: freeze)
    monkeypatch.setattr(
        materialize_module,
        "evaluate_expanding_temperature_calibration",
        lambda *args: calibration,
    )
    monkeypatch.setattr(
        materialize_module,
        "evaluate_score_models_walk_forward",
        lambda *args, **kwargs: score_models,
    )

    result = materialize_advanced_evaluation(
        tmp_path / "historical.json",
        tmp_path / "teams.json",
        tmp_path / "seasons.json",
        tmp_path,
    )

    assert calls == [str(tmp_path / "historical.json")]
    assert result.prediction_row_count == 42


def test_cli_prints_result_and_reports_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = AdvancedEvaluationMaterializationResult(
        predictions_path=tmp_path / "predictions.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        prediction_row_count=5320,
        predictions_sha256="a" * 64,
        manifest_sha256="b" * 64,
        calibration_strategy="temperature_scaling",
        status="written",
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_advanced_evaluation",
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
    assert json.loads(capsys.readouterr().out)["prediction_row_count"] == 5320

    monkeypatch.setattr(
        materialize_module,
        "materialize_advanced_evaluation",
        lambda *args: (_ for _ in ()).throw(AdvancedEvaluationError("invalid")),
    )
    with pytest.raises(SystemExit):
        main(arguments)
