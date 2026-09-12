"""Produce the first deterministic, multi-season training dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.features import PointInTimeFeatureRow
from pl_platform.domain.training import (
    TRAINING_ROW_SCHEMA_VERSION,
    TrainingExample,
    deterministic_training_example_id,
)
from pl_platform.features.materialize import (
    FeatureDatasetManifest,
    FeaturePredictorSchema,
    load_feature_dataset,
    materialize_feature_entries,
)
from pl_platform.ingestion.manifest import load_manifest

TRAINING_DATASET_SCHEMA_VERSION: Final = 1
TrainingMaterializationStatus = Literal["written", "already_current"]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class TrainingDatasetError(ValueError):
    """Verified feature datasets cannot form one consistent training dataset."""


class TrainingInputChecksums(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    historical_manifest_sha256: Sha256
    team_registry_sha256: Sha256
    season_registry_sha256: Sha256


class TrainingFeatureSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    feature_row_count: PositiveInt
    features_sha256: Sha256
    feature_manifest_sha256: Sha256
    canonical_dataset_id: str = Field(min_length=1)
    canonical_fixtures_sha256: Sha256
    historical_context_sha256: Sha256
    raw_source_id: str = Field(min_length=1)
    raw_artifact_id: str = Field(min_length=1)
    raw_sha256: Sha256
    raw_captured_at: datetime

    @field_validator("raw_captured_at")
    @classmethod
    def raw_captured_at_must_be_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            msg = "raw_captured_at must be timezone-aware UTC"
            raise ValueError(msg)
        return value


class TrainingTargetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Literal["full-time-result-and-score"]
    version: Literal[1]
    fields: tuple[
        Literal["outcome"],
        Literal["home_goals"],
        Literal["away_goals"],
    ]
    outcome_values: tuple[
        Literal["home_win"],
        Literal["draw"],
        Literal["away_win"],
    ]


class TrainingDatasetManifest(BaseModel):
    """Versioned lineage contract for the combined training dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: str = Field(min_length=1)
    competition_id: Literal["eng-premier-league"]
    season_ids: tuple[str, ...] = Field(min_length=1)
    training_row_count: PositiveInt
    training_sha256: Sha256
    training_row_schema_version: Literal[1]
    predictor_schema: FeaturePredictorSchema
    target_schema: TrainingTargetSchema
    ordered_by: tuple[
        Literal["kickoff_at"],
        Literal["training_example_id"],
    ]
    input_checksums: TrainingInputChecksums
    source_feature_datasets: tuple[TrainingFeatureSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sources_must_match_seasons_and_count(self) -> Self:
        if self.season_ids != tuple(sorted(set(self.season_ids))):
            msg = "training seasons must be unique and ordered"
            raise ValueError(msg)
        source_seasons = tuple(
            source.season_id for source in self.source_feature_datasets
        )
        if source_seasons != self.season_ids:
            msg = "feature source seasons do not match training seasons"
            raise ValueError(msg)
        source_ids = tuple(source.dataset_id for source in self.source_feature_datasets)
        if len(source_ids) != len(set(source_ids)):
            msg = "feature source dataset IDs must be unique"
            raise ValueError(msg)
        expected_count = sum(
            source.feature_row_count for source in self.source_feature_datasets
        )
        if self.training_row_count != expected_count:
            msg = "training-row count does not match feature source counts"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class TrainingMaterializationResult:
    training_rows_path: Path
    manifest_path: Path
    training_row_count: int
    training_sha256: str
    status: TrainingMaterializationStatus


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def training_examples_from_feature_rows(
    rows: Sequence[PointInTimeFeatureRow],
    feature_manifest: FeatureDatasetManifest,
) -> tuple[TrainingExample, ...]:
    """Project verified feature rows into model-ready examples."""

    examples: list[TrainingExample] = []
    expected_names = feature_manifest.predictor_schema.predictor_names
    for row in rows:
        if row.training_label is None:
            msg = f"feature row {row.id} has no training target"
            raise TrainingDatasetError(msg)
        if (
            row.competition_id != feature_manifest.competition_id
            or row.season_id != feature_manifest.season_id
        ):
            msg = f"feature row {row.id} does not match its feature dataset"
            raise TrainingDatasetError(msg)
        if (
            row.predictors.schema_id != feature_manifest.predictor_schema.id
            or row.predictors.schema_version
            != feature_manifest.predictor_schema.version
            or tuple(item.name for item in row.predictors.values) != expected_names
        ):
            msg = f"feature row {row.id} does not match its predictor schema"
            raise TrainingDatasetError(msg)
        example_id = deterministic_training_example_id(
            row.id,
            feature_manifest.dataset_id,
        )
        examples.append(
            TrainingExample(
                id=example_id,
                feature_row_id=row.id,
                fixture_id=row.fixture_id,
                competition_id="eng-premier-league",
                season_id=row.season_id,
                home_team_id=row.home_team_id,
                away_team_id=row.away_team_id,
                kickoff_at=row.kickoff_at,
                kickoff_precision=row.kickoff_precision,
                feature_cutoff_at=row.feature_cutoff_at,
                predictors=row.predictors,
                target=row.training_label,
                source_feature_dataset_id=feature_manifest.dataset_id,
            )
        )
    return tuple(examples)


def _stable_training_bytes(examples: Sequence[TrainingExample]) -> bytes:
    ordered = sorted(examples, key=lambda item: (item.kickoff_at, item.id))
    lines = (
        json.dumps(
            example.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for example in ordered
    )
    return ("\n".join(lines) + "\n").encode()


def _validate_training_examples(
    examples: Sequence[TrainingExample],
    predictor_schema: FeaturePredictorSchema,
    sources: Sequence[TrainingFeatureSource],
) -> None:
    if not examples:
        msg = "training dataset cannot be empty"
        raise TrainingDatasetError(msg)
    expected_count = sum(source.feature_row_count for source in sources)
    if len(examples) != expected_count:
        msg = f"expected {expected_count} training rows, found {len(examples)}"
        raise TrainingDatasetError(msg)
    for identities, message in (
        ((item.id for item in examples), "training-example IDs must be unique"),
        ((item.feature_row_id for item in examples), "feature-row IDs must be unique"),
        ((item.fixture_id for item in examples), "fixture IDs must be unique"),
    ):
        values = tuple(identities)
        if len(values) != len(set(values)):
            raise TrainingDatasetError(message)

    source_by_id = {source.dataset_id: source for source in sources}
    expected_names = predictor_schema.predictor_names
    for example in examples:
        source = source_by_id.get(example.source_feature_dataset_id)
        if source is None:
            msg = f"training example {example.id} references an unknown feature dataset"
            raise TrainingDatasetError(msg)
        if example.season_id != source.season_id:
            msg = f"training example {example.id} references another season's dataset"
            raise TrainingDatasetError(msg)
        if (
            example.predictors.schema_id != predictor_schema.id
            or example.predictors.schema_version != predictor_schema.version
            or tuple(item.name for item in example.predictors.values) != expected_names
        ):
            msg = f"training example {example.id} has inconsistent predictors"
            raise TrainingDatasetError(msg)


def _training_manifest_bytes(
    training_payload: bytes,
    examples: Sequence[TrainingExample],
    predictor_schema: FeaturePredictorSchema,
    sources: tuple[TrainingFeatureSource, ...],
    input_checksums: TrainingInputChecksums,
) -> bytes:
    season_ids = tuple(source.season_id for source in sources)
    manifest = TrainingDatasetManifest(
        dataset_schema_version=TRAINING_DATASET_SCHEMA_VERSION,
        dataset_id=(f"premier-league-training-{season_ids[0]}-to-{season_ids[-1]}"),
        competition_id="eng-premier-league",
        season_ids=season_ids,
        training_row_count=len(examples),
        training_sha256=_sha256(training_payload),
        training_row_schema_version=TRAINING_ROW_SCHEMA_VERSION,
        predictor_schema=predictor_schema,
        target_schema=TrainingTargetSchema(
            id="full-time-result-and-score",
            version=1,
            fields=("outcome", "home_goals", "away_goals"),
            outcome_values=("home_win", "draw", "away_win"),
        ),
        ordered_by=("kickoff_at", "training_example_id"),
        input_checksums=input_checksums,
        source_feature_datasets=sources,
    )
    return (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


def write_training_dataset(
    examples: Sequence[TrainingExample],
    output_directory: Path,
    predictor_schema: FeaturePredictorSchema,
    sources: tuple[TrainingFeatureSource, ...],
    input_checksums: TrainingInputChecksums,
) -> TrainingMaterializationResult:
    """Validate and atomically publish one deterministic training dataset."""

    _validate_training_examples(examples, predictor_schema, sources)
    training_payload = _stable_training_bytes(examples)
    manifest_payload = _training_manifest_bytes(
        training_payload,
        examples,
        predictor_schema,
        sources,
        input_checksums,
    )
    training_rows_path = output_directory / "training.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"
    is_current = (
        training_rows_path.exists()
        and manifest_path.exists()
        and training_rows_path.read_bytes() == training_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(training_rows_path, training_payload)
        _atomic_write(manifest_path, manifest_payload)
    return TrainingMaterializationResult(
        training_rows_path=training_rows_path,
        manifest_path=manifest_path,
        training_row_count=len(examples),
        training_sha256=_sha256(training_payload),
        status="already_current" if is_current else "written",
    )


def load_training_dataset(
    training_rows_path: Path,
    manifest_path: Path,
) -> tuple[tuple[TrainingExample, ...], TrainingDatasetManifest]:
    """Load training examples only after validating checksum and schema lineage."""

    manifest = TrainingDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    payload = training_rows_path.read_bytes()
    if _sha256(payload) != manifest.training_sha256:
        msg = "training checksum does not match its dataset manifest"
        raise TrainingDatasetError(msg)
    examples = tuple(
        TrainingExample.model_validate_json(line)
        for line in payload.decode().splitlines()
    )
    if len(examples) != manifest.training_row_count:
        msg = "training-row count does not match its dataset manifest"
        raise TrainingDatasetError(msg)
    _validate_training_examples(
        examples,
        manifest.predictor_schema,
        manifest.source_feature_datasets,
    )
    expected_seasons = set(manifest.season_ids)
    if {example.season_id for example in examples} != expected_seasons:
        msg = "training examples do not cover the manifest seasons"
        raise TrainingDatasetError(msg)
    return examples, manifest


def _feature_source(
    manifest: FeatureDatasetManifest,
    manifest_path: Path,
) -> TrainingFeatureSource:
    return TrainingFeatureSource(
        dataset_id=manifest.dataset_id,
        season_id=manifest.season_id,
        feature_row_count=manifest.feature_row_count,
        features_sha256=manifest.features_sha256,
        feature_manifest_sha256=_sha256(manifest_path.read_bytes()),
        canonical_dataset_id=manifest.canonical_source.dataset_id,
        canonical_fixtures_sha256=manifest.canonical_source.fixtures_sha256,
        historical_context_sha256=(manifest.historical_context.history_chain_sha256),
        raw_source_id=manifest.raw_source.source_id,
        raw_artifact_id=manifest.raw_source.artifact_id,
        raw_sha256=manifest.raw_source.sha256,
        raw_captured_at=manifest.raw_source.captured_at,
    )


def materialize_training_dataset(
    manifest_path: Path,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> TrainingMaterializationResult:
    """Verify and combine every manifest season into the first training set."""

    historical_manifest = load_manifest(manifest_path)
    examples: list[TrainingExample] = []
    sources: list[TrainingFeatureSource] = []
    predictor_schema: FeaturePredictorSchema | None = None
    feature_results = materialize_feature_entries(
        manifest_path,
        team_registry_path,
        season_registry_path,
        data_root,
    )
    if len(feature_results) != len(historical_manifest.files):
        msg = "feature materialization did not cover the historical manifest"
        raise TrainingDatasetError(msg)
    for entry, feature_result in zip(
        historical_manifest.files,
        feature_results,
        strict=True,
    ):
        rows, feature_manifest = load_feature_dataset(
            feature_result.feature_rows_path,
            feature_result.manifest_path,
        )
        expected_season_id = f"{entry.season_start:04d}-{entry.season_end:04d}"
        if feature_manifest.season_id != expected_season_id:
            msg = "feature dataset season does not match its historical entry"
            raise TrainingDatasetError(msg)
        if feature_manifest.raw_source.artifact_id != entry.id:
            msg = "feature dataset raw artifact does not match its historical entry"
            raise TrainingDatasetError(msg)
        if (
            feature_manifest.raw_source.source_id != historical_manifest.source.id
            or feature_manifest.raw_source.sha256 != entry.sha256
            or feature_manifest.raw_source.captured_at != entry.captured_at
        ):
            msg = "feature dataset raw lineage does not match the historical manifest"
            raise TrainingDatasetError(msg)
        if predictor_schema is None:
            predictor_schema = feature_manifest.predictor_schema
        elif feature_manifest.predictor_schema != predictor_schema:
            msg = "feature datasets do not share one predictor schema"
            raise TrainingDatasetError(msg)
        sources.append(_feature_source(feature_manifest, feature_result.manifest_path))
        examples.extend(training_examples_from_feature_rows(rows, feature_manifest))

    if predictor_schema is None:
        msg = "historical manifest contains no feature datasets"
        raise TrainingDatasetError(msg)
    input_checksums = TrainingInputChecksums(
        historical_manifest_sha256=_sha256(manifest_path.read_bytes()),
        team_registry_sha256=_sha256(team_registry_path.read_bytes()),
        season_registry_sha256=_sha256(season_registry_path.read_bytes()),
    )
    season_ids = tuple(source.season_id for source in sources)
    output_directory = (
        data_root
        / "processed"
        / "training"
        / "epl"
        / f"{season_ids[0]}_to_{season_ids[-1]}"
    )
    return write_training_dataset(
        examples,
        output_directory,
        predictor_schema,
        tuple(sources),
        input_checksums,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Produce the reproducible Premier League training dataset."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--seasons", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = materialize_training_dataset(
            arguments.manifest,
            arguments.teams,
            arguments.seasons,
            arguments.data_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    serialized = asdict(result)
    serialized["training_rows_path"] = str(result.training_rows_path)
    serialized["manifest_path"] = str(result.manifest_path)
    print(json.dumps(serialized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
