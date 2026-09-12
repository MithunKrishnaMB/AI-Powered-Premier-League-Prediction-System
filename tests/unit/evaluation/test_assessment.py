"""Tests for frozen Step 3.9 gates and Step 3.10 explanations."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

import pl_platform.evaluation.assessment as assessment_module
from pl_platform.evaluation.advanced_materialize import (
    AdvancedEvaluationManifest,
    load_advanced_evaluation_dataset,
)
from pl_platform.evaluation.assessment import (
    AcceptanceContract,
    AcceptanceReport,
    ModelAssessmentError,
    _method_metric,
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
from tests.unit.evaluation.helpers import PREDICTOR_NAMES, complete_corpus

ROOT = Path(__file__).parents[3]
EVALUATION_ROOT = ROOT / "data" / "processed" / "evaluation" / "epl"


def _source_manifests() -> tuple[
    EvaluationDatasetManifest,
    CatBoostTuningDatasetManifest,
    AdvancedEvaluationManifest,
]:
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
    return base, catboost, advanced


def test_acceptance_uses_complete_identical_folds_and_selects_catboost() -> None:
    report = build_acceptance_report(*_source_manifests())

    assert report.champion_method == "catboost"
    assert report.accepted_methods == (
        "elo",
        "multinomial_logistic",
        "catboost",
        "poisson",
        "dixon_coles",
    )
    assert all(candidate.complete_coverage for candidate in report.candidates)
    assert all(candidate.log_loss_fold_wins >= 3 for candidate in report.candidates)
    assert report.baseline_aggregate_metric.prediction_count == 1900


def test_acceptance_contract_and_derived_results_fail_closed() -> None:
    with pytest.raises(ValidationError, match="thresholds are frozen"):
        AcceptanceContract(minimum_relative_log_loss_improvement=0.01)
    report = build_acceptance_report(*_source_manifests())
    payload = report.model_dump(mode="json")
    payload["champion_method"] = "elo"
    with pytest.raises(ValidationError, match="champion"):
        AcceptanceReport.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["candidates"][0]["accepted"] = False
    with pytest.raises(ValidationError, match="gate result"):
        AcceptanceReport.model_validate(payload)

    with pytest.raises(ModelAssessmentError, match="missing aggregate"):
        _method_metric((), "elo")


def test_global_explanations_are_model_appropriate_and_target_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, catboost, advanced = _source_manifests()
    logistic = SimpleNamespace(
        coefficients=np.asarray(
            ((0.1, -0.1, 0.0), (0.6, -0.2, -0.4), (0.2, 0.0, -0.2))
        ),
        intercepts=np.asarray((0.3, -0.1, -0.2)),
        diagnostics=SimpleNamespace(converged=True),
    )
    fitted_catboost = SimpleNamespace(
        normalized_feature_importances=lambda: (0.2, 0.7, 0.1)
    )
    fitted_poisson = SimpleNamespace(
        team_ids=(complete_corpus()[0].home_team_id, complete_corpus()[0].away_team_id),
        attack=np.asarray((0.3, -0.3)),
        defence=np.asarray((-0.2, 0.2)),
        intercept=0.1,
        home_advantage=0.25,
    )
    monkeypatch.setattr(
        assessment_module,
        "fit_multinomial_logistic_regression",
        lambda *args: logistic,
    )
    monkeypatch.setattr(
        assessment_module, "fit_catboost_classifier", lambda *args: fitted_catboost
    )
    monkeypatch.setattr(
        assessment_module, "fit_independent_poisson", lambda *args: fitted_poisson
    )
    monkeypatch.setattr(
        assessment_module,
        "fit_dixon_coles_rho",
        lambda *args: SimpleNamespace(rho=-0.05),
    )
    development = tuple(
        row for row in complete_corpus() if row.season_id != "2025-2026"
    )

    result = build_global_explanations(
        development, PREDICTOR_NAMES, base, catboost, advanced
    )

    assert result.development_training_row_count == 30
    assert result.logistic_predictors[0].predictor_name == "feature_signal"
    assert result.catboost_predictors[0].predictor_name == "feature_signal"
    assert sum(
        row.normalized_prediction_values_change for row in result.catboost_predictors
    ) == pytest.approx(1.0)
    assert tuple(row.team_id for row in result.poisson_teams) == tuple(
        sorted(
            (
                complete_corpus()[0].home_team_id,
                complete_corpus()[0].away_team_id,
            ),
            key=str,
        )
    )
    assert "target" not in result.model_dump_json()


def test_global_explanations_reject_empty_and_nonconverged_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, catboost, advanced = _source_manifests()
    with pytest.raises(ModelAssessmentError, match="require development"):
        build_global_explanations((), PREDICTOR_NAMES, base, catboost, advanced)

    monkeypatch.setattr(
        assessment_module,
        "fit_multinomial_logistic_regression",
        lambda *args: SimpleNamespace(diagnostics=SimpleNamespace(converged=False)),
    )
    development = tuple(
        row for row in complete_corpus() if row.season_id != "2025-2026"
    )
    with pytest.raises(ModelAssessmentError, match="did not converge"):
        build_global_explanations(
            development, PREDICTOR_NAMES, base, catboost, advanced
        )
