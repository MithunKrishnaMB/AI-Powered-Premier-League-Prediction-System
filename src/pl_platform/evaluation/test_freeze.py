"""Formal, target-free freeze contract for the untouched test season."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.training import TrainingExample
from pl_platform.training.materialize import TrainingDatasetManifest

TEST_FREEZE_SCHEMA_VERSION: Final = 1
UNTOUCHED_TEST_SEASONS: Final = ("2025-2026",)
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class TestFreezeError(ValueError):
    """The untouched test boundary or its source lineage is inconsistent."""


class UntouchedTestFreeze(BaseModel):
    """Immutable identity and policy for data excluded from development work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    id: Literal["untouched-test-2025-2026-v1"]
    status: Literal["frozen_untouched"]
    competition_id: Literal["eng-premier-league"]
    season_ids: tuple[Literal["2025-2026"]]
    test_row_count: Annotated[int, Field(strict=True, ge=1)]
    ordered_by: tuple[
        Literal["feature_cutoff_at"],
        Literal["kickoff_at"],
        Literal["training_example_id"],
    ]
    test_example_identities_sha256: Sha256
    source_training_dataset_id: str = Field(min_length=1)
    source_training_sha256: Sha256
    source_training_manifest_sha256: Sha256
    target_access_policy: Literal[
        "prohibited_until_explicit_one_time_final_test_evaluation"
    ]
    development_use_policy: Literal[
        "excluded_from_training_tuning_selection_calibration_and_acceptance"
    ]

    @model_validator(mode="after")
    def freeze_must_use_the_supported_boundary(self) -> Self:
        if self.season_ids != UNTOUCHED_TEST_SEASONS:
            msg = "test freeze must contain only the 2025-2026 season"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class TestFreezeMaterializationResult:
    manifest_path: Path
    manifest_sha256: str
    status: Literal["written", "already_current"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_test_identity_bytes(examples: Sequence[TrainingExample]) -> bytes:
    ordered = sorted(
        examples,
        key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id),
    )
    lines = []
    for example in ordered:
        predictor_payload = json.dumps(
            example.predictors.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        identity = {
            "feature_cutoff_at": example.feature_cutoff_at.isoformat(),
            "feature_row_id": str(example.feature_row_id),
            "fixture_id": str(example.fixture_id),
            "kickoff_at": example.kickoff_at.isoformat(),
            "predictors_sha256": _sha256(predictor_payload),
            "season_id": example.season_id,
            "source_feature_dataset_id": example.source_feature_dataset_id,
            "training_example_id": str(example.id),
        }
        lines.append(
            json.dumps(
                identity,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return ("\n".join(lines) + "\n").encode()


def build_test_freeze(
    examples: Sequence[TrainingExample],
    source_training_manifest: TrainingDatasetManifest,
    source_training_manifest_sha256: str,
) -> UntouchedTestFreeze:
    """Freeze test identities without reading or serializing their targets."""

    test_examples = tuple(
        example for example in examples if example.season_id in UNTOUCHED_TEST_SEASONS
    )
    if not test_examples:
        msg = "training corpus has no rows for the untouched test season"
        raise TestFreezeError(msg)
    if {example.season_id for example in test_examples} != set(UNTOUCHED_TEST_SEASONS):
        msg = "training corpus does not cover the complete test-season contract"
        raise TestFreezeError(msg)
    expected_count = sum(
        source.feature_row_count
        for source in source_training_manifest.source_feature_datasets
        if source.season_id in UNTOUCHED_TEST_SEASONS
    )
    if len(test_examples) != expected_count:
        msg = "test row count does not match verified feature provenance"
        raise TestFreezeError(msg)
    identity_payload = _stable_test_identity_bytes(test_examples)
    return UntouchedTestFreeze(
        schema_version=TEST_FREEZE_SCHEMA_VERSION,
        id="untouched-test-2025-2026-v1",
        status="frozen_untouched",
        competition_id="eng-premier-league",
        season_ids=UNTOUCHED_TEST_SEASONS,
        test_row_count=len(test_examples),
        ordered_by=("feature_cutoff_at", "kickoff_at", "training_example_id"),
        test_example_identities_sha256=_sha256(identity_payload),
        source_training_dataset_id=source_training_manifest.dataset_id,
        source_training_sha256=source_training_manifest.training_sha256,
        source_training_manifest_sha256=source_training_manifest_sha256,
        target_access_policy=(
            "prohibited_until_explicit_one_time_final_test_evaluation"
        ),
        development_use_policy=(
            "excluded_from_training_tuning_selection_calibration_and_acceptance"
        ),
    )


def _stable_manifest_bytes(freeze: UntouchedTestFreeze) -> bytes:
    return (
        json.dumps(freeze.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_test_freeze(
    freeze: UntouchedTestFreeze,
    output_directory: Path,
) -> TestFreezeMaterializationResult:
    """Publish a deterministic standalone freeze manifest."""

    payload = _stable_manifest_bytes(freeze)
    manifest_path = output_directory / "freeze-manifest.json"
    is_current = manifest_path.exists() and manifest_path.read_bytes() == payload
    if not is_current:
        _atomic_write(manifest_path, payload)
    return TestFreezeMaterializationResult(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(payload),
        status="already_current" if is_current else "written",
    )


def load_test_freeze(path: Path) -> UntouchedTestFreeze:
    """Load the typed freeze contract from deterministic JSON bytes."""

    payload = path.read_bytes()
    freeze = UntouchedTestFreeze.model_validate_json(payload)
    if _stable_manifest_bytes(freeze) != payload:
        msg = "test freeze manifest bytes are not deterministic"
        raise TestFreezeError(msg)
    return freeze
