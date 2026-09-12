"""Tests for CatBoost tuning and untouched-test artifact materialization."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import pl_platform.evaluation.catboost_materialize as materialize_module
from pl_platform.evaluation.catboost_materialize import (
    CatBoostTuningDatasetError,
    CatBoostTuningDatasetManifest,
    CatBoostTuningMaterializationResult,
    load_catboost_tuning_dataset,
    main,
    materialize_catboost_tuning,
    write_catboost_tuning_dataset,
)
from pl_platform.evaluation.catboost_model import CatBoostParameters
from pl_platform.evaluation.catboost_tuning import (
    CatBoostTuningResult,
    tune_catboost_with_walk_forward,
)
from pl_platform.evaluation.test_freeze import (
    TestFreezeMaterializationResult as FreezeMaterializationResult,
)
from pl_platform.evaluation.test_freeze import (
    UntouchedTestFreeze,
    build_test_freeze,
    write_test_freeze,
)
from pl_platform.training.materialize import (
    TrainingDatasetManifest,
    TrainingMaterializationResult,
)
from tests.unit.evaluation.helpers import (
    PREDICTOR_NAMES,
    SOURCE_TRAINING_SHA256,
    complete_corpus,
    make_training_manifest,
    training_manifest_payload,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidates() -> tuple[CatBoostParameters, ...]:
    return tuple(
        CatBoostParameters(
            id=identifier,
            iterations=3,
            depth=depth,
            learning_rate=0.1,
            l2_leaf_reg=3.0,
        )
        for identifier, depth in (
            ("catboost-small-a", 2),
            ("catboost-small-b", 3),
            ("catboost-small-c", 4),
        )
    )


def _artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    TrainingDatasetManifest,
    str,
    UntouchedTestFreeze,
    FreezeMaterializationResult,
    CatBoostTuningResult,
]:
    candidates = _candidates()
    monkeypatch.setattr(materialize_module, "CATBOOST_CANDIDATES", candidates)
    examples = complete_corpus()
    source_manifest = make_training_manifest()
    source_payload = training_manifest_payload(source_manifest)
    source_sha256 = _sha256(source_payload)
    freeze = build_test_freeze(examples, source_manifest, source_sha256)
    freeze_result = write_test_freeze(freeze, tmp_path / "test-freeze")
    tuning = tune_catboost_with_walk_forward(
        examples,
        PREDICTOR_NAMES,
        source_training_dataset_id=source_manifest.dataset_id,
        source_training_sha256=source_manifest.training_sha256,
        candidates=candidates,
    )
    return source_manifest, source_sha256, freeze, freeze_result, tuning


def test_writes_loads_and_reuses_catboost_tuning_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, source_sha, freeze, freeze_result, tuning = _artifacts(
        tmp_path,
        monkeypatch,
    )
    output = tmp_path / "tuning"
    arguments = (
        output,
        source,
        source_sha,
        freeze,
        freeze_result.manifest_path,
        freeze_result.manifest_sha256,
    )

    first = write_catboost_tuning_dataset(tuning, *arguments)
    reversed_tuning = replace(
        tuning,
        selected_predictions=tuple(reversed(tuning.selected_predictions)),
    )
    second = write_catboost_tuning_dataset(reversed_tuning, *arguments)
    predictions, manifest = load_catboost_tuning_dataset(
        first.predictions_path,
        first.manifest_path,
    )

    assert first.status == "written"
    assert second.status == "already_current"
    assert len(predictions) == 15
    assert manifest.selected_candidate_id == tuning.selected_candidate_id
    assert manifest.test_freeze == freeze
    assert manifest.final_development_fit.training_row_count == 30


def test_catboost_loader_rejects_changed_prediction_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, source_sha, freeze, freeze_result, tuning = _artifacts(
        tmp_path,
        monkeypatch,
    )
    result = write_catboost_tuning_dataset(
        tuning,
        tmp_path / "tuning",
        source,
        source_sha,
        freeze,
        freeze_result.manifest_path,
        freeze_result.manifest_sha256,
    )
    result.predictions_path.write_bytes(result.predictions_path.read_bytes() + b"\n")

    with pytest.raises(CatBoostTuningDatasetError, match="checksum"):
        load_catboost_tuning_dataset(result.predictions_path, result.manifest_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("freeze_lineage", "test freeze does not match"),
        ("freeze_count", "test freeze row count"),
        ("fold_boundary", "unsupported fold boundary"),
        ("fold_diagnostics", "fold diagnostics"),
        ("final_diagnostics", "final CatBoost fit diagnostics"),
    ),
)
def test_manifest_rejects_temporal_and_lineage_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    source, source_sha, freeze, freeze_result, tuning = _artifacts(
        tmp_path,
        monkeypatch,
    )
    result = write_catboost_tuning_dataset(
        tuning,
        tmp_path / "tuning",
        source,
        source_sha,
        freeze,
        freeze_result.manifest_path,
        freeze_result.manifest_sha256,
    )
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if mutation == "freeze_lineage":
        payload["test_freeze"]["source_training_dataset_id"] = "different"
    elif mutation == "freeze_count":
        payload["test_freeze"]["test_row_count"] -= 1
    elif mutation == "fold_boundary":
        payload["candidates"][0]["folds"][0]["id"] = "different"
    elif mutation == "fold_diagnostics":
        payload["candidates"][0]["folds"][0]["fit"]["training_row_count"] += 1
    else:
        payload["final_development_fit"]["training_row_count"] += 1
    payload["test_freeze_manifest_sha256"] = _sha256(
        (json.dumps(payload["test_freeze"], indent=2, sort_keys=True) + "\n").encode()
    )

    with pytest.raises(ValueError, match=message):
        CatBoostTuningDatasetManifest.model_validate(payload)


def test_orchestrator_reverifies_training_and_writes_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, _, tuning = _artifacts(tmp_path, monkeypatch)
    training_manifest_path = tmp_path / "training-manifest.json"
    training_manifest_path.write_bytes(training_manifest_payload(source))
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

    monkeypatch.setattr(materialize_module, "materialize_training_dataset", reverify)
    monkeypatch.setattr(
        materialize_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), source),
    )
    monkeypatch.setattr(
        materialize_module,
        "tune_catboost_with_walk_forward",
        lambda *args, **kwargs: tuning,
    )

    result = materialize_catboost_tuning(
        tmp_path / "historical.json",
        tmp_path / "teams.json",
        tmp_path / "seasons.json",
        tmp_path,
    )

    assert calls == [str(tmp_path / "historical.json")]
    assert result.test_freeze_manifest_path.exists()
    assert result.selected_prediction_row_count == 15


def test_cli_prints_result_and_reports_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = CatBoostTuningMaterializationResult(
        predictions_path=tmp_path / "predictions.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        test_freeze_manifest_path=tmp_path / "freeze-manifest.json",
        selected_candidate_id="catboost-small-a",
        selected_prediction_row_count=1900,
        selected_predictions_sha256="a" * 64,
        manifest_sha256="b" * 64,
        test_freeze_manifest_sha256="c" * 64,
        status="written",
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_catboost_tuning",
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
    assert json.loads(capsys.readouterr().out)["selected_prediction_row_count"] == 1900

    def fail(*args: object) -> CatBoostTuningMaterializationResult:
        raise CatBoostTuningDatasetError("invalid CatBoost tuning")

    monkeypatch.setattr(materialize_module, "materialize_catboost_tuning", fail)
    with pytest.raises(SystemExit):
        main(arguments)
