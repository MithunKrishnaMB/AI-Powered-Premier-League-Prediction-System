"""Canonical candidate-retraining manifest contract."""

import json

from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.training.retraining import (
    CandidateRetrainingManifest,
    CandidateRetrainingWorkflow,
)
from tests.unit.training.test_retraining import (
    _baseline,
    _baseline_examples,
    _feature_and_result,
    _Fitter,
)


def test_candidate_manifest_is_canonical_unassessed_and_nonpromotional() -> None:
    feature, result = _feature_and_result()
    candidate = CandidateRetrainingWorkflow(fitter=_Fitter()).run(
        baseline=_baseline(feature),
        baseline_examples=_baseline_examples(feature),
        features=(feature,),
        results=(result,),
    )
    exact = canonical_json_bytes(candidate.manifest)
    payload = json.loads(exact)

    assert CandidateRetrainingManifest.model_validate(payload) == candidate.manifest
    assert sha256_bytes(exact) == candidate.manifest_sha256
    assert payload["status"] == "candidate_unassessed"
    assert payload["excluded_season_ids"] == ["2025-2026"]
    assert {
        "artifact_components",
        "metrics",
        "promotion",
        "registry_entry_id",
        "scoreline_distribution",
    }.isdisjoint(payload)
