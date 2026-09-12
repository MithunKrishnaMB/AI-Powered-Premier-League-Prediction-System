"""Tests for deterministic Steps 3.9-3.10 assessment materialization."""

import json
from pathlib import Path

import pytest

import pl_platform.evaluation.assessment_materialize as materialize_module
from pl_platform.evaluation.advanced_materialize import (
    load_advanced_evaluation_dataset,
)
from pl_platform.evaluation.assessment_materialize import (
    ModelAssessmentDatasetError,
    ModelAssessmentManifest,
    ModelAssessmentMaterializationResult,
    _validate_comparable_prediction_populations,
    _validate_source_lineage,
    load_model_assessment,
    main,
    materialize_model_assessment,
    write_model_assessment,
)
from pl_platform.evaluation.catboost_materialize import (
    load_catboost_tuning_dataset,
)
from pl_platform.evaluation.materialize import load_evaluation_dataset
from pl_platform.training.materialize import TrainingMaterializationResult
from tests.unit.evaluation.helpers import complete_corpus

ROOT = Path(__file__).parents[3]
EVALUATION_ROOT = ROOT / "data" / "processed" / "evaluation" / "epl"
ASSESSMENT_PATH = (
    EVALUATION_ROOT
    / "model-assessment-2015-2016_to_2024-2025"
    / "assessment-manifest.json"
)


def test_writer_loader_and_idempotence_preserve_canonical_bytes(
    tmp_path: Path,
) -> None:
    source = load_model_assessment(ASSESSMENT_PATH)
    first = write_model_assessment(
        tmp_path,
        source.source_training_manifest,
        source.sources,
        source.acceptance,
        source.explanations,
    )
    second = write_model_assessment(
        tmp_path,
        source.source_training_manifest,
        source.sources,
        source.acceptance,
        source.explanations,
    )
    loaded = load_model_assessment(first.manifest_path)

    assert first.status == "written"
    assert second.status == "already_current"
    assert loaded.acceptance.champion_method == "catboost"
    assert first.manifest_sha256 == second.manifest_sha256


def test_loader_rejects_noncanonical_bytes(tmp_path: Path) -> None:
    payload = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "assessment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelAssessmentDatasetError, match="not deterministic"):
        load_model_assessment(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("development", "development window"),
        ("test", "untouched test window"),
        ("training", "training manifest"),
        ("count", "naive explanation counts"),
        ("predictor", "predictor schema"),
        ("importance", "sum to one"),
        ("teams", "unique and ordered"),
    ),
)
def test_manifest_rejects_population_and_explanation_drift(
    mutation: str,
    message: str,
) -> None:
    payload = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    if mutation == "development":
        payload["development_season_ids"] = payload["development_season_ids"][:-1]
    elif mutation == "test":
        payload["untouched_test_season_ids"] = ["2024-2025"]
    elif mutation == "training":
        payload["sources"]["training_manifest_sha256"] = "0" * 64
    elif mutation == "count":
        payload["explanations"]["development_training_row_count"] -= 1
    elif mutation == "predictor":
        payload["explanations"]["logistic_predictors"][0]["predictor_name"] = "unknown"
    elif mutation == "importance":
        payload["explanations"]["catboost_predictors"][0][
            "normalized_prediction_values_change"
        ] += 0.1
    else:
        payload["explanations"]["poisson_teams"] = tuple(
            reversed(payload["explanations"]["poisson_teams"])
        )

    with pytest.raises(ValueError, match=message):
        ModelAssessmentManifest.model_validate(payload)


def test_source_lineage_validation_rejects_stale_evaluation() -> None:
    assessment = load_model_assessment(ASSESSMENT_PATH)
    base_dir = EVALUATION_ROOT / "development-2015-2016_to_2024-2025"
    _, base = load_evaluation_dataset(
        base_dir / "predictions.jsonl", base_dir / "dataset-manifest.json"
    )
    cat_dir = EVALUATION_ROOT / "catboost-tuning-2015-2016_to_2024-2025"
    _, catboost = load_catboost_tuning_dataset(
        cat_dir / "selected-predictions.jsonl", cat_dir / "dataset-manifest.json"
    )
    advanced_dir = EVALUATION_ROOT / "advanced-development-2015-2016_to_2024-2025"
    _, advanced = load_advanced_evaluation_dataset(
        advanced_dir / "predictions.jsonl", advanced_dir / "dataset-manifest.json"
    )
    changed = base.model_copy(update={"source_training_manifest_sha256": "0" * 64})

    with pytest.raises(ModelAssessmentDatasetError, match="verified training"):
        _validate_source_lineage(
            assessment.source_training_manifest,
            assessment.sources.training_manifest_sha256,
            changed,
            catboost,
            advanced,
        )


def test_prediction_population_validation_rejects_missing_fixture() -> None:
    base_dir = EVALUATION_ROOT / "development-2015-2016_to_2024-2025"
    base_predictions, _ = load_evaluation_dataset(
        base_dir / "predictions.jsonl", base_dir / "dataset-manifest.json"
    )
    cat_dir = EVALUATION_ROOT / "catboost-tuning-2015-2016_to_2024-2025"
    catboost_predictions, _ = load_catboost_tuning_dataset(
        cat_dir / "selected-predictions.jsonl", cat_dir / "dataset-manifest.json"
    )
    advanced_dir = EVALUATION_ROOT / "advanced-development-2015-2016_to_2024-2025"
    advanced_predictions, _ = load_advanced_evaluation_dataset(
        advanced_dir / "predictions.jsonl", advanced_dir / "dataset-manifest.json"
    )
    _validate_comparable_prediction_populations(
        base_predictions, catboost_predictions, advanced_predictions
    )

    with pytest.raises(ModelAssessmentDatasetError, match="fold identities"):
        _validate_comparable_prediction_populations(
            base_predictions,
            catboost_predictions[:-1],
            advanced_predictions,
        )


def _seed_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ModelAssessmentManifest:
    assessment = load_model_assessment(ASSESSMENT_PATH)
    source_paths = {
        "development-2015-2016_to_2024-2025/dataset-manifest.json": (
            EVALUATION_ROOT
            / "development-2015-2016_to_2024-2025"
            / "dataset-manifest.json"
        ),
        "catboost-tuning-2015-2016_to_2024-2025/dataset-manifest.json": (
            EVALUATION_ROOT
            / "catboost-tuning-2015-2016_to_2024-2025"
            / "dataset-manifest.json"
        ),
        "advanced-development-2015-2016_to_2024-2025/dataset-manifest.json": (
            EVALUATION_ROOT
            / "advanced-development-2015-2016_to_2024-2025"
            / "dataset-manifest.json"
        ),
        "test-2025-2026/freeze-manifest.json": (
            EVALUATION_ROOT / "test-2025-2026" / "freeze-manifest.json"
        ),
    }
    for relative, source_path in source_paths.items():
        destination = tmp_path / "processed" / "evaluation" / "epl" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
    training_path = tmp_path / "training-manifest.json"
    training_path.write_bytes(
        (
            json.dumps(
                assessment.source_training_manifest.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    training_result = TrainingMaterializationResult(
        training_rows_path=tmp_path / "training.jsonl",
        manifest_path=training_path,
        training_row_count=4180,
        training_sha256=assessment.source_training_manifest.training_sha256,
        status="already_current",
    )
    base_dir = EVALUATION_ROOT / "development-2015-2016_to_2024-2025"
    base_predictions, base = load_evaluation_dataset(
        base_dir / "predictions.jsonl", base_dir / "dataset-manifest.json"
    )
    cat_dir = EVALUATION_ROOT / "catboost-tuning-2015-2016_to_2024-2025"
    catboost_predictions, catboost = load_catboost_tuning_dataset(
        cat_dir / "selected-predictions.jsonl", cat_dir / "dataset-manifest.json"
    )
    advanced_dir = EVALUATION_ROOT / "advanced-development-2015-2016_to_2024-2025"
    advanced_predictions, advanced = load_advanced_evaluation_dataset(
        advanced_dir / "predictions.jsonl", advanced_dir / "dataset-manifest.json"
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_training_dataset",
        lambda *args: training_result,
    )
    monkeypatch.setattr(
        materialize_module,
        "load_training_dataset",
        lambda *args: (complete_corpus(), assessment.source_training_manifest),
    )
    monkeypatch.setattr(
        materialize_module,
        "load_evaluation_dataset",
        lambda *args: (base_predictions, base),
    )
    monkeypatch.setattr(
        materialize_module,
        "load_catboost_tuning_dataset",
        lambda *args: (catboost_predictions, catboost),
    )
    monkeypatch.setattr(
        materialize_module,
        "load_advanced_evaluation_dataset",
        lambda *args: (advanced_predictions, advanced),
    )
    monkeypatch.setattr(
        materialize_module, "load_test_freeze", lambda *args: catboost.test_freeze
    )
    monkeypatch.setattr(
        materialize_module,
        "build_acceptance_report",
        lambda *args: assessment.acceptance,
    )
    monkeypatch.setattr(
        materialize_module,
        "build_global_explanations",
        lambda *args: assessment.explanations,
    )
    return assessment


def test_orchestrator_reverifies_sources_without_opening_test_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_orchestrator(tmp_path, monkeypatch)

    result = materialize_model_assessment(
        tmp_path / "raw-manifest.json",
        tmp_path / "teams.json",
        tmp_path / "seasons.json",
        tmp_path,
    )

    assert result.champion_method == "catboost"
    assert result.manifest_path.exists()


def test_cli_reports_success_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = ModelAssessmentMaterializationResult(
        manifest_path=tmp_path / "assessment.json",
        manifest_sha256="a" * 64,
        champion_method="catboost",
        accepted_methods=("catboost",),
        status="written",
    )
    monkeypatch.setattr(
        materialize_module, "materialize_model_assessment", lambda *args: expected
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
    assert json.loads(capsys.readouterr().out)["champion_method"] == "catboost"

    def fail(*args: object) -> ModelAssessmentMaterializationResult:
        raise ModelAssessmentDatasetError("invalid assessment")

    monkeypatch.setattr(materialize_module, "materialize_model_assessment", fail)
    with pytest.raises(SystemExit):
        main(arguments)
