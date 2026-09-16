"""Explicit deterministic candidate-retraining workflow tests."""

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast
from uuid import UUID

import numpy as np
import numpy.typing as npt
import pytest
from pydantic import ValidationError

from pl_platform.domain.fixtures import FixtureScore, FixtureStatus
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.catboost_model import (
    CatBoostFitDiagnostics,
    CatBoostParameters,
    FittedCatBoostClassifier,
)
from pl_platform.evaluation.walk_forward import DEVELOPMENT_SEASONS, EXCLUDED_SEASONS
from pl_platform.features.materialize import FeaturePredictorSchema
from pl_platform.prediction.domain import CompletedResultEvidence, UpcomingFeatureRow
from pl_platform.prediction.lifecycle import build_upcoming_feature_rows
from pl_platform.registry.artifact_manifest import (
    ComponentIntegrity,
    build_model_artifact_manifest,
    canonical_json_bytes,
    sha256_bytes,
)
from pl_platform.training.retraining import (
    RETRAINING_PARAMETERS,
    CandidateRetrainingError,
    CandidateRetrainingFailureCode,
    CandidateRetrainingManifest,
    CandidateRetrainingWorkflow,
    RetrainingBaseline,
)
from tests.unit.evaluation.helpers import complete_corpus
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.registry.helpers import artifact_provenance


class _UnusedModel:
    def __init__(self) -> None:
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
        return np.zeros((len(features), 3), dtype=np.float64)

    def get_feature_importance(self, *, type: str) -> object:
        return np.ones(1, dtype=np.float64)

    def save_model(self, fname: str, *, format: str) -> None:
        raise AssertionError("candidate workflow does not serialize the classifier")


@dataclass
class _Fitter:
    fail: bool = False
    bad_diagnostics: bool = False
    calls: list[tuple[tuple[TrainingExample, ...], tuple[str, ...]]] = field(
        default_factory=list
    )

    def __call__(
        self,
        examples: object,
        predictor_names: tuple[str, ...],
        parameters: CatBoostParameters,
    ) -> FittedCatBoostClassifier:
        typed = tuple(cast(tuple[TrainingExample, ...], examples))
        self.calls.append((typed, predictor_names))
        assert parameters == RETRAINING_PARAMETERS
        if self.fail:
            raise ValueError("synthetic fit failure")
        return FittedCatBoostClassifier(
            predictor_names=predictor_names,
            model=_UnusedModel(),
            diagnostics=CatBoostFitDiagnostics(
                candidate_id=("wrong" if self.bad_diagnostics else parameters.id),
                tree_count=parameters.iterations,
                predictor_count=len(predictor_names),
                training_row_count=len(typed),
            ),
        )


def _feature_and_result() -> tuple[UpcomingFeatureRow, CompletedResultEvidence]:
    upcoming, prior, season, priors, ratings = feature_inputs()
    feature = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(prior,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    score = FixtureScore(home=3, away=1)
    result = CompletedResultEvidence(
        fixture=upcoming.fixture.model_copy(
            update={
                "status": FixtureStatus.FINISHED,
                "full_time_score": score,
                "outcome": score.outcome,
            }
        ),
        result_id=UUID(int=8001),
        result_identity_sha256="7" * 64,
        observation_id=UUID(int=8002),
        cache_key_sha256="8" * 64,
        retrieved_at=upcoming.fixture.kickoff_at + timedelta(hours=3),
    )
    return feature, result


def _schema(feature: UpcomingFeatureRow) -> FeaturePredictorSchema:
    names = tuple(item.name for item in feature.predictors.values)
    payload = json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode()
    return FeaturePredictorSchema(
        id="epl-pre-match",
        version=2,
        predictor_count=len(names),
        predictor_names=names,
        predictor_names_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _baseline(feature: UpcomingFeatureRow) -> RetrainingBaseline:
    return RetrainingBaseline(
        model_id=UUID(int=9001),
        artifact_id=UUID(int=9002),
        manifest_id=UUID(int=9003),
        artifact_manifest_sha256="9" * 64,
        source_training_manifest_sha256="a" * 64,
        predictor_schema=_schema(feature),
        configuration=RETRAINING_PARAMETERS,
        development_season_ids=DEVELOPMENT_SEASONS,
        excluded_season_ids=EXCLUDED_SEASONS,
    )


def _baseline_examples(feature: UpcomingFeatureRow) -> tuple[TrainingExample, ...]:
    return tuple(
        item.model_copy(update={"predictors": feature.predictors})
        for item in complete_corpus()
        if item.season_id in DEVELOPMENT_SEASONS
    )


def test_candidate_retraining_is_deterministic_unassessed_and_target_safe() -> None:
    feature, result = _feature_and_result()
    baseline = _baseline(feature)
    examples = _baseline_examples(feature)
    fitter = _Fitter()
    workflow = CandidateRetrainingWorkflow(fitter=fitter)

    first = workflow.run(
        baseline=baseline,
        baseline_examples=examples,
        features=(feature,),
        results=(result,),
    )
    second = workflow.run(
        baseline=baseline,
        baseline_examples=tuple(reversed(examples)),
        features=(feature,),
        results=(result,),
    )

    assert first.manifest == second.manifest
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest.status == "candidate_unassessed"
    assert first.manifest.excluded_season_ids == ("2025-2026",)
    assert first.manifest.operational_season_ids == ("2026-2027",)
    assert first.manifest.operational_row_count == 1
    assert first.manifest.combined_row_count == len(examples) + 1
    assert first.manifest.knowledge_cutoff_at == result.retrieved_at
    assert fitter.calls[0][0][-1].target.home_goals == 3
    assert first.classifier.diagnostics.training_row_count == len(examples) + 1
    assert {
        "metrics",
        "promotion",
        "registry_entry_id",
        "scoreline_distribution",
    }.isdisjoint(first.manifest.model_fields_set)


def test_retraining_baseline_can_only_derive_from_exact_artifact_manifest() -> None:
    provenance = artifact_provenance()
    manifest = build_model_artifact_manifest(
        provenance,
        preprocessor_integrity=ComponentIntegrity(
            byte_count=1,
            sha256="b" * 64,
        ),
        classifier_integrity=ComponentIntegrity(
            byte_count=1,
            sha256="c" * 64,
        ),
    )
    checksum = sha256_bytes(canonical_json_bytes(manifest))

    baseline = RetrainingBaseline.from_artifact(
        manifest,
        manifest_sha256=checksum,
    )

    assert baseline.model_id == manifest.model_id
    assert baseline.configuration == RETRAINING_PARAMETERS
    with pytest.raises(CandidateRetrainingError) as captured:
        RetrainingBaseline.from_artifact(manifest, manifest_sha256="0" * 64)
    assert captured.value.code is CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE


@pytest.mark.parametrize("missing", ("features", "results"))
def test_retraining_requires_complete_nonempty_operational_pairs(missing: str) -> None:
    feature, result = _feature_and_result()
    with pytest.raises(CandidateRetrainingError) as captured:
        CandidateRetrainingWorkflow(fitter=_Fitter()).run(
            baseline=_baseline(feature),
            baseline_examples=_baseline_examples(feature),
            features=() if missing == "features" else (feature,),
            results=() if missing == "results" else (result,),
        )
    assert captured.value.code is CandidateRetrainingFailureCode.EMPTY_OPERATIONAL_INPUT


def test_retraining_rejects_duplicates_and_incomplete_pairing() -> None:
    feature, result = _feature_and_result()
    workflow = CandidateRetrainingWorkflow(fitter=_Fitter())
    baseline = _baseline(feature)
    baseline_examples = _baseline_examples(feature)
    for features, results, code in (
        (
            (feature, feature),
            (result,),
            CandidateRetrainingFailureCode.DUPLICATE_IDENTITY,
        ),
        (
            (feature,),
            (result, result),
            CandidateRetrainingFailureCode.DUPLICATE_IDENTITY,
        ),
        (
            (feature,),
            (
                result.model_copy(
                    update={
                        "fixture": result.fixture.model_copy(
                            update={"id": UUID(int=42)}
                        )
                    }
                ),
            ),
            CandidateRetrainingFailureCode.FEATURE_RESULT_MISMATCH,
        ),
    ):
        with pytest.raises(CandidateRetrainingError) as captured:
            workflow.run(
                baseline=baseline,
                baseline_examples=baseline_examples,
                features=features,
                results=results,
            )
        assert captured.value.code is code


def test_retraining_rejects_incompatible_baseline_and_predictors() -> None:
    feature, result = _feature_and_result()
    workflow = CandidateRetrainingWorkflow(fitter=_Fitter())
    baseline = _baseline(feature)
    examples = _baseline_examples(feature)
    cases = (
        ((), CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE),
        (
            (*examples, examples[0]),
            CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
        ),
        (
            tuple(item for item in examples if item.season_id != "2015-2016"),
            CandidateRetrainingFailureCode.BASELINE_INCOMPATIBLE,
        ),
        (
            (
                *examples,
                complete_corpus()[-1].model_copy(
                    update={"predictors": feature.predictors}
                ),
            ),
            CandidateRetrainingFailureCode.SEALED_TARGET_PROHIBITED,
        ),
    )
    for changed, code in cases:
        with pytest.raises(CandidateRetrainingError) as captured:
            workflow.run(
                baseline=baseline,
                baseline_examples=changed,
                features=(feature,),
                results=(result,),
            )
        assert captured.value.code is code

    changed_example = examples[0].model_copy(
        update={"predictors": complete_corpus()[0].predictors}
    )
    with pytest.raises(CandidateRetrainingError) as predictor_error:
        workflow.run(
            baseline=baseline,
            baseline_examples=(changed_example, *examples[1:]),
            features=(feature,),
            results=(result,),
        )
    assert (
        predictor_error.value.code
        is CandidateRetrainingFailureCode.PREDICTOR_SCHEMA_INCOMPATIBLE
    )


def test_retraining_rejects_mismatch_chronology_sealed_and_fixture_reuse() -> None:
    feature, result = _feature_and_result()
    baseline = _baseline(feature)
    examples = _baseline_examples(feature)
    workflow = CandidateRetrainingWorkflow(fitter=_Fitter())

    mismatched = result.model_copy(
        update={
            "fixture": result.fixture.model_copy(
                update={"home_team_id": UUID(int=123456)}
            )
        }
    )
    early = result.model_copy(
        update={"retrieved_at": feature.kickoff_at - timedelta(seconds=1)}
    )
    for changed_feature, changed_result, code in (
        (feature, mismatched, CandidateRetrainingFailureCode.FEATURE_RESULT_MISMATCH),
        (feature, early, CandidateRetrainingFailureCode.CHRONOLOGY_VIOLATION),
    ):
        with pytest.raises(CandidateRetrainingError) as captured:
            workflow.run(
                baseline=baseline,
                baseline_examples=examples,
                features=(changed_feature,),
                results=(changed_result,),
            )
        assert captured.value.code is code

    sealed_feature = feature.model_copy(update={"season_id": "2025-2026"})
    sealed_result = result.model_copy(
        update={"fixture": result.fixture.model_copy(update={"season_id": "2025-2026"})}
    )
    with pytest.raises(CandidateRetrainingError) as sealed:
        workflow.run(
            baseline=baseline,
            baseline_examples=examples,
            features=(sealed_feature,),
            results=(sealed_result,),
        )
    assert sealed.value.code is CandidateRetrainingFailureCode.SEALED_TARGET_PROHIBITED

    reused = examples[0].model_copy(update={"fixture_id": feature.fixture_id})
    with pytest.raises(CandidateRetrainingError) as duplicate:
        workflow.run(
            baseline=baseline,
            baseline_examples=(reused, *examples[1:]),
            features=(feature,),
            results=(result,),
        )
    assert duplicate.value.code is CandidateRetrainingFailureCode.DUPLICATE_IDENTITY


@pytest.mark.parametrize("bad_diagnostics", (False, True))
def test_retraining_wraps_fit_failures_and_rejects_bad_diagnostics(
    bad_diagnostics: bool,
) -> None:
    feature, result = _feature_and_result()
    fitter = _Fitter(fail=not bad_diagnostics, bad_diagnostics=bad_diagnostics)
    with pytest.raises(CandidateRetrainingError) as captured:
        CandidateRetrainingWorkflow(fitter=fitter).run(
            baseline=_baseline(feature),
            baseline_examples=_baseline_examples(feature),
            features=(feature,),
            results=(result,),
        )
    assert captured.value.code is CandidateRetrainingFailureCode.FIT_FAILED


def test_candidate_manifest_rejects_identity_drift() -> None:
    feature, result = _feature_and_result()
    created = CandidateRetrainingWorkflow(fitter=_Fitter()).run(
        baseline=_baseline(feature),
        baseline_examples=_baseline_examples(feature),
        features=(feature,),
        results=(result,),
    )
    with pytest.raises(ValidationError, match="candidate ID"):
        CandidateRetrainingManifest.model_validate(
            {**created.manifest.model_dump(), "candidate_id": UUID(int=0)}
        )


def test_retraining_import_does_not_fit_write_or_open_dependencies() -> None:
    script = """
import pl_platform.evaluation.catboost_model as model
def fail(*args, **kwargs):
    raise AssertionError("retraining import performed runtime work")
model.fit_catboost_classifier = fail
import pl_platform.training.retraining
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
