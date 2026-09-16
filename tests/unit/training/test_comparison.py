"""Deterministic candidate comparison and passive observability tests."""

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
import numpy.typing as npt
import pytest
from pydantic import ValidationError

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.domain.fixtures import FixtureScore, FixtureStatus
from pl_platform.prediction.domain import CompletedResultEvidence, UpcomingFeatureRow
from pl_platform.prediction.lifecycle import build_upcoming_feature_rows
from pl_platform.training.comparison import (
    CandidateComparisonError,
    CandidateComparisonFailureCode,
    CandidateComparisonReport,
    CandidateComparisonResult,
    CandidateComparisonWorkflow,
)
from pl_platform.training.monitoring import build_retraining_operational_snapshot
from pl_platform.training.retraining import (
    CandidateRetrainingResult,
    CandidateRetrainingWorkflow,
    RetrainingBaseline,
)
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.training.test_retraining import (
    _baseline,
    _baseline_examples,
    _feature_and_result,
    _Fitter,
)


class _ConstantModel:
    def __init__(self, probabilities: tuple[float, float, float]) -> None:
        self._probabilities = probabilities
        self.tree_count_ = 200
        self.classes_ = np.asarray((0, 1, 2), dtype=np.int64)
        self.feature_names_: list[str] = []

    def fit(
        self,
        features: npt.NDArray[np.float64],
        targets: npt.NDArray[np.int64],
    ) -> object:
        return self

    def predict_proba(self, features: npt.NDArray[np.float64]) -> object:
        return np.asarray([self._probabilities] * len(features), dtype=np.float64)

    def get_feature_importance(self, *, type: str) -> object:
        return np.ones(1, dtype=np.float64)

    def save_model(self, fname: str, *, format: str) -> None:
        raise AssertionError("comparison does not serialize classifiers")


class _Classifier:
    def __init__(
        self,
        predictor_names: tuple[str, ...],
        probabilities: tuple[float, float, float],
    ) -> None:
        self.predictor_names = predictor_names
        self.probabilities = probabilities

    def predict_probabilities(self, predictors: object) -> OutcomeProbabilities:
        return OutcomeProbabilities(
            home_win=self.probabilities[0],
            draw=self.probabilities[1],
            away_win=self.probabilities[2],
        )


def _candidate(
    candidate_probabilities: tuple[float, float, float] = (0.75, 0.125, 0.125),
) -> tuple[RetrainingBaseline, CandidateRetrainingResult]:
    feature, result = _feature_and_result()
    baseline = _baseline(feature)
    created = CandidateRetrainingWorkflow(fitter=_Fitter()).run(
        baseline=baseline,
        baseline_examples=_baseline_examples(feature),
        features=(feature,),
        results=(result,),
    )
    classifier = replace(
        created.classifier,
        model=_ConstantModel(candidate_probabilities),
    )
    return baseline, replace(created, classifier=classifier)


def _comparison_pairs(
    count: int,
) -> tuple[tuple[UpcomingFeatureRow, ...], tuple[CompletedResultEvidence, ...]]:
    upcoming, prior, season, priors, ratings = feature_inputs()
    features: list[UpcomingFeatureRow] = []
    results: list[CompletedResultEvidence] = []
    cutoff = datetime(2026, 9, 25, 8, tzinfo=UTC)
    for index in range(count):
        kickoff = datetime(2026, 10, 1, 14, tzinfo=UTC) + timedelta(days=index)
        fixture_id = UUID(int=20_000 + index)
        fixture = upcoming.fixture.model_copy(
            update={"id": fixture_id, "kickoff_at": kickoff}
        )
        evidence = upcoming.model_copy(
            update={
                "fixture": fixture,
                "revision_id": UUID(int=30_000 + index),
                "observation_id": UUID(int=40_000 + index),
                "batch_id": UUID(int=50_000 + index),
                "batch_member_ordinal": 0,
                "retrieved_at": cutoff,
                "knowledge_available_at": cutoff,
            }
        )
        feature = build_upcoming_feature_rows(
            fixtures=(evidence,),
            completed_results=(prior,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )[0]
        if index < max(1, count - 6):
            score = FixtureScore(home=2, away=0)
        elif index < count - 3:
            score = FixtureScore(home=1, away=1)
        else:
            score = FixtureScore(home=0, away=1)
        result = CompletedResultEvidence(
            fixture=fixture.model_copy(
                update={
                    "status": FixtureStatus.FINISHED,
                    "full_time_score": score,
                    "outcome": score.outcome,
                }
            ),
            result_id=UUID(int=60_000 + index),
            result_identity_sha256=f"{70_000 + index:064x}",
            observation_id=UUID(int=80_000 + index),
            cache_key_sha256=f"{90_000 + index:064x}",
            retrieved_at=kickoff + timedelta(hours=3),
        )
        features.append(feature)
        results.append(result)
    return tuple(features), tuple(results)


def _comparison_result(
    count: int = 30,
    *,
    baseline_probabilities: tuple[float, float, float] = (0.34, 0.33, 0.33),
    candidate_probabilities: tuple[float, float, float] = (0.75, 0.125, 0.125),
) -> CandidateComparisonResult:
    baseline, candidate = _candidate(candidate_probabilities)
    features, results = _comparison_pairs(count)
    classifier = _Classifier(
        baseline.predictor_schema.predictor_names,
        baseline_probabilities,
    )
    return CandidateComparisonWorkflow().run(
        baseline=baseline,
        baseline_classifier=classifier,
        candidate=candidate,
        features=features,
        results=results,
    )


def test_comparison_recommends_review_without_changing_registry() -> None:
    first = _comparison_result()
    second = _comparison_result()

    assert first == second
    assert first.report.decision == "candidate_review_recommended"
    assert first.report.minimum_population_passed
    assert first.report.outcome_coverage_passed
    assert first.report.registry_disposition == "no_change"
    assert first.report.human_review_required
    assert first.report.comparison_row_count == 30
    assert first.report.comparison_season_ids == ("2026-2027",)


def test_comparison_reports_insufficient_evidence_and_retains_baseline() -> None:
    insufficient = _comparison_result(count=1)
    retained = _comparison_result(
        baseline_probabilities=(0.75, 0.125, 0.125),
        candidate_probabilities=(0.34, 0.33, 0.33),
    )

    assert insufficient.report.decision == "insufficient_evidence"
    assert not insufficient.report.minimum_population_passed
    assert retained.report.decision == "retain_baseline"
    assert not retained.report.log_loss_improvement_passed


def test_comparison_rejects_empty_duplicate_mismatched_and_overlap_inputs() -> None:
    baseline, candidate = _candidate()
    features, results = _comparison_pairs(2)
    classifier = _Classifier(
        baseline.predictor_schema.predictor_names, (0.34, 0.33, 0.33)
    )
    workflow = CandidateComparisonWorkflow()
    cases = (
        ((), (), CandidateComparisonFailureCode.EMPTY_COMPARISON_INPUT),
        (
            (features[0], features[0]),
            (results[0],),
            CandidateComparisonFailureCode.DUPLICATE_IDENTITY,
        ),
        (
            (features[0],),
            (results[1],),
            CandidateComparisonFailureCode.FEATURE_RESULT_MISMATCH,
        ),
    )
    for changed_features, changed_results, expected in cases:
        with pytest.raises(CandidateComparisonError) as captured:
            workflow.run(
                baseline=baseline,
                baseline_classifier=classifier,
                candidate=candidate,
                features=changed_features,
                results=changed_results,
            )
        assert captured.value.code is expected

    trained_fixture = candidate.manifest.operational_examples[0].fixture_id
    with pytest.raises(CandidateComparisonError) as overlap:
        workflow.run(
            baseline=baseline,
            baseline_classifier=classifier,
            candidate=candidate,
            features=(features[0].model_copy(update={"fixture_id": trained_fixture}),),
            results=(
                results[0].model_copy(
                    update={
                        "fixture": results[0].fixture.model_copy(
                            update={"id": trained_fixture}
                        )
                    }
                ),
            ),
        )
    assert overlap.value.code is CandidateComparisonFailureCode.TRAINING_OVERLAP


def test_comparison_rejects_sealed_chronology_schema_and_candidate_drift() -> None:
    baseline, candidate = _candidate()
    features, results = _comparison_pairs(1)
    classifier = _Classifier(
        baseline.predictor_schema.predictor_names, (0.34, 0.33, 0.33)
    )
    workflow = CandidateComparisonWorkflow()

    sealed_feature = features[0].model_copy(update={"season_id": "2025-2026"})
    sealed_result = results[0].model_copy(
        update={
            "fixture": results[0].fixture.model_copy(update={"season_id": "2025-2026"})
        }
    )
    with pytest.raises(CandidateComparisonError) as sealed:
        workflow.run(
            baseline=baseline,
            baseline_classifier=classifier,
            candidate=candidate,
            features=(sealed_feature,),
            results=(sealed_result,),
        )
    assert sealed.value.code is CandidateComparisonFailureCode.SEALED_TARGET_PROHIBITED

    early = features[0].model_copy(
        update={"feature_cutoff_at": candidate.manifest.knowledge_cutoff_at}
    )
    with pytest.raises(CandidateComparisonError) as chronology:
        workflow.run(
            baseline=baseline,
            baseline_classifier=classifier,
            candidate=candidate,
            features=(early,),
            results=results,
        )
    assert chronology.value.code is CandidateComparisonFailureCode.CHRONOLOGY_VIOLATION

    bad_classifier = _Classifier(("wrong",), (0.34, 0.33, 0.33))
    with pytest.raises(CandidateComparisonError) as schema:
        workflow.run(
            baseline=baseline,
            baseline_classifier=bad_classifier,
            candidate=candidate,
            features=features,
            results=results,
        )
    assert (
        schema.value.code
        is CandidateComparisonFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE
    )

    drifted = replace(candidate, manifest_sha256="0" * 64)
    with pytest.raises(CandidateComparisonError) as drift:
        workflow.run(
            baseline=baseline,
            baseline_classifier=classifier,
            candidate=drifted,
            features=features,
            results=results,
        )
    assert drift.value.code is CandidateComparisonFailureCode.CANDIDATE_INCOMPATIBLE


def test_comparison_wraps_prediction_failure_and_rejects_report_drift() -> None:
    baseline, candidate = _candidate((0.0, 0.0, 0.0))
    features, results = _comparison_pairs(1)
    classifier = _Classifier(
        baseline.predictor_schema.predictor_names, (0.34, 0.33, 0.33)
    )
    with pytest.raises(CandidateComparisonError) as captured:
        CandidateComparisonWorkflow().run(
            baseline=baseline,
            baseline_classifier=classifier,
            candidate=candidate,
            features=features,
            results=results,
        )
    assert captured.value.code is CandidateComparisonFailureCode.PREDICTION_FAILED

    report = _comparison_result().report
    with pytest.raises(ValidationError, match="decision"):
        CandidateComparisonReport.model_validate(
            {**report.model_dump(), "decision": "retain_baseline"}
        )


@pytest.mark.parametrize(
    ("decision", "severity"),
    (
        ("insufficient_evidence", "warning"),
        ("retain_baseline", "info"),
        ("candidate_review_recommended", "action_required"),
    ),
)
def test_passive_operational_snapshot_maps_decisions_without_activation(
    decision: str,
    severity: str,
) -> None:
    if decision == "insufficient_evidence":
        compared = _comparison_result(count=1)
    elif decision == "retain_baseline":
        compared = _comparison_result(
            baseline_probabilities=(0.75, 0.125, 0.125),
            candidate_probabilities=(0.34, 0.33, 0.33),
        )
    else:
        compared = _comparison_result()
    observed_at = compared.report.comparison_knowledge_cutoff_at + timedelta(minutes=1)

    snapshot = build_retraining_operational_snapshot(
        compared.report,
        report_sha256=compared.report_sha256,
        observed_at=observed_at,
    )

    assert snapshot.registry_state == "development_accepted"
    assert snapshot.active_model_count == 0
    assert snapshot.execution_mode == "explicit_manual_only"
    assert snapshot.signals[1].severity == severity


def test_passive_snapshot_rejects_checksum_and_chronology_drift() -> None:
    compared = _comparison_result(count=1)
    with pytest.raises(ValueError, match="checksum"):
        build_retraining_operational_snapshot(
            compared.report,
            report_sha256="0" * 64,
            observed_at=compared.report.comparison_knowledge_cutoff_at,
        )
    with pytest.raises(ValueError, match="precedes"):
        build_retraining_operational_snapshot(
            compared.report,
            report_sha256=compared.report_sha256,
            observed_at=compared.report.comparison_knowledge_cutoff_at
            - timedelta(seconds=1),
        )


def test_comparison_and_monitoring_imports_have_no_runtime_side_effects() -> None:
    script = """
import pl_platform.evaluation.catboost_model as model
def fail(*args, **kwargs):
    raise AssertionError("import performed model or runtime work")
model.fit_catboost_classifier = fail
import pl_platform.training.comparison
import pl_platform.training.monitoring
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
