"""Passive operational snapshot contracts; no polling or background execution."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.training.comparison import CandidateComparisonReport

OPERATIONAL_SNAPSHOT_SCHEMA_VERSION: Final = 1
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SignalSeverity = Literal["info", "warning", "action_required"]


class OperationalSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "registry_unchanged",
        "comparison_evidence_incomplete",
        "baseline_retained",
        "candidate_requires_human_review",
        "manual_execution_only",
    ]
    severity: SignalSeverity
    message: str = Field(min_length=1)


class RetrainingOperationalSnapshotPayload(BaseModel):
    """One explicitly built observation; it has no collection side effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["pl-platform-retraining-operational-snapshot"] = (
        "pl-platform-retraining-operational-snapshot"
    )
    schema_version: Literal[1] = OPERATIONAL_SNAPSHOT_SCHEMA_VERSION
    observed_at: datetime
    comparison_report_id: UUID
    comparison_report_sha256: Sha256
    candidate_id: UUID
    registry_state: Literal["development_accepted"] = "development_accepted"
    active_model_count: Literal[0] = 0
    comparison_decision: Literal[
        "insufficient_evidence",
        "retain_baseline",
        "candidate_review_recommended",
    ]
    signals: tuple[OperationalSignal, ...] = Field(min_length=3, max_length=3)
    execution_mode: Literal["explicit_manual_only"] = "explicit_manual_only"

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("operational observation time must be UTC")
        return value

    @model_validator(mode="after")
    def signal_set_must_match_decision(self) -> Self:
        expected_middle = {
            "insufficient_evidence": (
                "comparison_evidence_incomplete",
                "warning",
            ),
            "retain_baseline": ("baseline_retained", "info"),
            "candidate_review_recommended": (
                "candidate_requires_human_review",
                "action_required",
            ),
        }[self.comparison_decision]
        expected = (
            ("registry_unchanged", "info"),
            expected_middle,
            ("manual_execution_only", "info"),
        )
        actual = tuple((item.code, item.severity) for item in self.signals)
        if actual != expected:
            raise ValueError("operational signals do not match comparison decision")
        return self


class RetrainingOperationalSnapshot(RetrainingOperationalSnapshotPayload):
    snapshot_id: UUID

    @model_validator(mode="after")
    def snapshot_identity_must_match_payload(self) -> Self:
        payload = RetrainingOperationalSnapshotPayload.model_validate(
            self.model_dump(exclude={"snapshot_id"})
        )
        if self.snapshot_id != deterministic_operational_snapshot_id(payload):
            raise ValueError("operational snapshot ID does not match its payload")
        return self


def deterministic_operational_snapshot_id(
    payload: RetrainingOperationalSnapshotPayload,
) -> UUID:
    digest = sha256_bytes(canonical_json_bytes(payload))
    return uuid5(
        NAMESPACE_URL,
        f"pl-platform:retraining-operational-snapshot:"
        f"{OPERATIONAL_SNAPSHOT_SCHEMA_VERSION}|{digest}",
    )


def build_retraining_operational_snapshot(
    report: CandidateComparisonReport,
    *,
    report_sha256: str,
    observed_at: datetime,
) -> RetrainingOperationalSnapshot:
    """Build a passive observation while preserving the actual registry state."""

    if sha256_bytes(canonical_json_bytes(report)) != report_sha256:
        raise ValueError("comparison report checksum is incompatible")
    if observed_at < report.comparison_knowledge_cutoff_at:
        raise ValueError("operational observation precedes comparison knowledge")
    middle = {
        "insufficient_evidence": OperationalSignal(
            code="comparison_evidence_incomplete",
            severity="warning",
            message="comparison evidence is below the deterministic review gate",
        ),
        "retain_baseline": OperationalSignal(
            code="baseline_retained",
            severity="info",
            message="comparison gates retain the development-accepted baseline",
        ),
        "candidate_review_recommended": OperationalSignal(
            code="candidate_requires_human_review",
            severity="action_required",
            message=(
                "candidate passed comparison gates but cannot change registry state"
            ),
        ),
    }[report.decision]
    payload = RetrainingOperationalSnapshotPayload(
        observed_at=observed_at,
        comparison_report_id=report.report_id,
        comparison_report_sha256=report_sha256,
        candidate_id=report.candidate_id,
        comparison_decision=report.decision,
        signals=(
            OperationalSignal(
                code="registry_unchanged",
                severity="info",
                message=(
                    "registry remains development_accepted with zero active models"
                ),
            ),
            middle,
            OperationalSignal(
                code="manual_execution_only",
                severity="info",
                message=(
                    "no scheduler, monitor loop, CI/CD or notification is configured"
                ),
            ),
        ),
    )
    return RetrainingOperationalSnapshot(
        **payload.model_dump(),
        snapshot_id=deterministic_operational_snapshot_id(payload),
    )
