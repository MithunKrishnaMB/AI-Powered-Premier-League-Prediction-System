"""Canonical candidate-comparison and operational-snapshot contracts."""

import json
from datetime import timedelta

from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.training.comparison import CandidateComparisonReport
from pl_platform.training.monitoring import (
    RetrainingOperationalSnapshot,
    build_retraining_operational_snapshot,
)
from tests.unit.training.test_comparison import _comparison_result


def test_comparison_report_is_canonical_and_explicitly_nonmutating() -> None:
    compared = _comparison_result()
    exact = canonical_json_bytes(compared.report)
    payload = json.loads(exact)

    assert CandidateComparisonReport.model_validate(payload) == compared.report
    assert sha256_bytes(exact) == compared.report_sha256
    assert payload["decision"] == "candidate_review_recommended"
    assert payload["registry_disposition"] == "no_change"
    assert payload["human_review_required"] is True
    assert {
        "active_registry_event",
        "artifact_components",
        "final_test_evidence",
        "scoreline_distribution",
    }.isdisjoint(payload)


def test_operational_snapshot_is_canonical_passive_and_no_active_model() -> None:
    compared = _comparison_result(count=1)
    snapshot = build_retraining_operational_snapshot(
        compared.report,
        report_sha256=compared.report_sha256,
        observed_at=compared.report.comparison_knowledge_cutoff_at
        + timedelta(seconds=1),
    )
    exact = canonical_json_bytes(snapshot)
    payload = json.loads(exact)

    assert RetrainingOperationalSnapshot.model_validate(payload) == snapshot
    assert payload["registry_state"] == "development_accepted"
    assert payload["active_model_count"] == 0
    assert payload["execution_mode"] == "explicit_manual_only"
    assert {"schedule", "notification", "deployment"}.isdisjoint(payload)
