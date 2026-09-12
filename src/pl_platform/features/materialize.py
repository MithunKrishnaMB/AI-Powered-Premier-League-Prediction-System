"""Materialize deterministic point-in-time feature datasets with lineage."""

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

from pl_platform.domain.features import (
    FEATURE_ROW_SCHEMA_VERSION,
    CanonicalDatasetProvenance,
    PointInTimeFeatureRow,
    SourceArtifactProvenance,
)
from pl_platform.domain.fixtures import Fixture
from pl_platform.domain.seasons import load_season_registry
from pl_platform.domain.teams import load_team_registry
from pl_platform.features.engine import (
    FORM_WINDOW_MATCHES,
    PREDICTOR_SCHEMA_ID,
    PREDICTOR_SCHEMA_VERSION,
    build_point_in_time_feature_rows,
)
from pl_platform.ingestion.manifest import HistoricalFile, load_manifest
from pl_platform.ingestion.materialize import materialize_historical_entry

FEATURE_DATASET_SCHEMA_VERSION: Final = 1
FEATURE_CHRONOLOGY_VERSION: Final = 1
FeatureMaterializationStatus = Literal["written", "already_current"]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PredictorName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class FeatureDatasetError(ValueError):
    """Canonical inputs or feature rows violate dataset lineage guarantees."""


class FeaturePredictorSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Literal["epl-pre-match"]
    version: Literal[1]
    predictor_count: PositiveInt
    predictor_names: tuple[PredictorName, ...] = Field(min_length=1)
    predictor_names_sha256: Sha256

    @model_validator(mode="after")
    def names_must_match_count_order_and_checksum(self) -> Self:
        if len(self.predictor_names) != self.predictor_count:
            msg = "predictor count does not match predictor names"
            raise ValueError(msg)
        if self.predictor_names != tuple(sorted(set(self.predictor_names))):
            msg = "predictor names must be unique and ordered"
            raise ValueError(msg)
        names_payload = json.dumps(
            self.predictor_names,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if _sha256(names_payload) != self.predictor_names_sha256:
            msg = "predictor-name checksum does not match predictor names"
            raise ValueError(msg)
        return self


class FeatureProcessingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chronology_version: Literal[1]
    date_only_batch_timezone: Literal["Europe/London"]
    form_window_matches: Literal[5]
    season_state_resets: Literal[True]


class FeatureCanonicalSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    dataset_schema_version: PositiveInt
    fixture_count: PositiveInt
    fixtures_sha256: Sha256
    team_registry_schema_version: PositiveInt
    season_registry_schema_version: PositiveInt


class FeatureRawSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    sha256: Sha256
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            msg = "captured_at must be timezone-aware UTC"
            raise ValueError(msg)
        return value


class FeatureDatasetManifest(BaseModel):
    """Versioned lineage contract for one processed feature dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal[1]
    dataset_id: str = Field(min_length=1)
    competition_id: Literal["eng-premier-league"]
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    feature_row_count: PositiveInt
    features_sha256: Sha256
    feature_row_schema_version: Literal[1]
    predictor_schema: FeaturePredictorSchema
    processing: FeatureProcessingContract
    canonical_source: FeatureCanonicalSource
    raw_source: FeatureRawSource


class _CanonicalSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str = Field(min_length=1)
    sha256: Sha256
    captured_at: datetime


class _CanonicalDatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: PositiveInt
    dataset_id: str = Field(min_length=1)
    competition_id: str = Field(min_length=1)
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    fixture_count: PositiveInt
    fixtures_sha256: Sha256
    source: _CanonicalSource
    team_registry_schema_version: PositiveInt
    season_registry_schema_version: PositiveInt


@dataclass(frozen=True, slots=True)
class FeatureMaterializationResult:
    feature_rows_path: Path
    manifest_path: Path
    feature_row_count: int
    features_sha256: str
    status: FeatureMaterializationStatus


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


def _stable_feature_bytes(rows: Sequence[PointInTimeFeatureRow]) -> bytes:
    ordered = sorted(
        rows,
        key=lambda row: (row.feature_cutoff_at, row.kickoff_at, row.id),
    )
    lines = (
        json.dumps(
            row.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for row in ordered
    )
    return ("\n".join(lines) + "\n").encode()


def _predictor_names(rows: Sequence[PointInTimeFeatureRow]) -> tuple[str, ...]:
    expected = tuple(item.name for item in rows[0].predictors.values)
    if not expected:
        msg = "feature rows require at least one approved predictor"
        raise FeatureDatasetError(msg)
    for row in rows[1:]:
        names = tuple(item.name for item in row.predictors.values)
        if names != expected:
            msg = "feature rows do not share one predictor schema"
            raise FeatureDatasetError(msg)
    return expected


def _validate_feature_rows(
    rows: Sequence[PointInTimeFeatureRow],
    provenance: CanonicalDatasetProvenance,
    *,
    source_fixture_count: int,
) -> tuple[str, ...]:
    if len(rows) != source_fixture_count:
        msg = (
            f"expected {source_fixture_count} feature rows from canonical fixtures, "
            f"found {len(rows)}"
        )
        raise FeatureDatasetError(msg)
    if not rows:
        msg = "feature dataset cannot be empty"
        raise FeatureDatasetError(msg)

    row_ids = [row.id for row in rows]
    fixture_ids = [row.fixture_id for row in rows]
    if len(row_ids) != len(set(row_ids)):
        msg = "feature-row IDs must be unique"
        raise FeatureDatasetError(msg)
    if len(fixture_ids) != len(set(fixture_ids)):
        msg = "feature rows must reference unique fixtures"
        raise FeatureDatasetError(msg)

    for row in rows:
        if row.provenance != provenance:
            msg = f"feature row {row.id} has inconsistent source provenance"
            raise FeatureDatasetError(msg)
        if (
            row.predictors.schema_id != PREDICTOR_SCHEMA_ID
            or row.predictors.schema_version != PREDICTOR_SCHEMA_VERSION
        ):
            msg = f"feature row {row.id} has an unsupported predictor schema"
            raise FeatureDatasetError(msg)
        if row.training_label is None:
            msg = f"historical feature row {row.id} requires a training label"
            raise FeatureDatasetError(msg)
    return _predictor_names(rows)


def _feature_manifest_bytes(
    rows_payload: bytes,
    rows: Sequence[PointInTimeFeatureRow],
    provenance: CanonicalDatasetProvenance,
    predictor_names: tuple[str, ...],
    *,
    source_fixture_count: int,
) -> bytes:
    predictor_names_payload = json.dumps(
        predictor_names,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    manifest = FeatureDatasetManifest(
        dataset_schema_version=FEATURE_DATASET_SCHEMA_VERSION,
        dataset_id=f"point-in-time-features-{provenance.season_id}",
        competition_id="eng-premier-league",
        season_id=provenance.season_id,
        feature_row_count=len(rows),
        features_sha256=_sha256(rows_payload),
        feature_row_schema_version=FEATURE_ROW_SCHEMA_VERSION,
        predictor_schema=FeaturePredictorSchema(
            id=PREDICTOR_SCHEMA_ID,
            version=PREDICTOR_SCHEMA_VERSION,
            predictor_count=len(predictor_names),
            predictor_names=predictor_names,
            predictor_names_sha256=_sha256(predictor_names_payload),
        ),
        processing=FeatureProcessingContract(
            chronology_version=FEATURE_CHRONOLOGY_VERSION,
            date_only_batch_timezone="Europe/London",
            form_window_matches=FORM_WINDOW_MATCHES,
            season_state_resets=True,
        ),
        canonical_source=FeatureCanonicalSource(
            dataset_id=provenance.dataset_id,
            dataset_schema_version=provenance.dataset_schema_version,
            fixture_count=source_fixture_count,
            fixtures_sha256=provenance.fixtures_sha256,
            team_registry_schema_version=provenance.team_registry_schema_version,
            season_registry_schema_version=provenance.season_registry_schema_version,
        ),
        raw_source=FeatureRawSource(
            source_id=provenance.source.source_id,
            artifact_id=provenance.source.artifact_id,
            sha256=provenance.source.sha256,
            captured_at=provenance.source.captured_at,
        ),
    )
    payload = manifest.model_dump(mode="json")
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def load_feature_dataset(
    feature_rows_path: Path,
    manifest_path: Path,
) -> tuple[tuple[PointInTimeFeatureRow, ...], FeatureDatasetManifest]:
    """Load feature rows only after validating their manifest and checksum."""

    manifest = FeatureDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    rows_payload = feature_rows_path.read_bytes()
    if _sha256(rows_payload) != manifest.features_sha256:
        msg = "feature-row checksum does not match its dataset manifest"
        raise FeatureDatasetError(msg)
    rows = tuple(
        PointInTimeFeatureRow.model_validate_json(line)
        for line in rows_payload.decode().splitlines()
    )
    if len(rows) != manifest.feature_row_count:
        msg = "feature-row count does not match its dataset manifest"
        raise FeatureDatasetError(msg)
    expected_names = manifest.predictor_schema.predictor_names
    for row in rows:
        names = tuple(item.name for item in row.predictors.values)
        if names != expected_names:
            msg = f"feature row {row.id} does not match the manifest predictor schema"
            raise FeatureDatasetError(msg)
        if row.competition_id != manifest.competition_id:
            msg = f"feature row {row.id} has inconsistent competition lineage"
            raise FeatureDatasetError(msg)
        if row.season_id != manifest.season_id:
            msg = f"feature row {row.id} has inconsistent season lineage"
            raise FeatureDatasetError(msg)
        if (
            row.provenance.dataset_id != manifest.canonical_source.dataset_id
            or row.provenance.fixtures_sha256
            != manifest.canonical_source.fixtures_sha256
            or row.provenance.source.artifact_id != manifest.raw_source.artifact_id
            or row.provenance.source.sha256 != manifest.raw_source.sha256
        ):
            msg = f"feature row {row.id} has inconsistent source lineage"
            raise FeatureDatasetError(msg)
    return rows, manifest


def write_feature_dataset(
    rows: Sequence[PointInTimeFeatureRow],
    output_directory: Path,
    provenance: CanonicalDatasetProvenance,
    *,
    source_fixture_count: int,
) -> FeatureMaterializationResult:
    """Validate and atomically publish deterministic feature rows and lineage."""

    predictor_names = _validate_feature_rows(
        rows,
        provenance,
        source_fixture_count=source_fixture_count,
    )
    rows_payload = _stable_feature_bytes(rows)
    manifest_payload = _feature_manifest_bytes(
        rows_payload,
        rows,
        provenance,
        predictor_names,
        source_fixture_count=source_fixture_count,
    )
    feature_rows_path = output_directory / "features.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"
    is_current = (
        feature_rows_path.exists()
        and manifest_path.exists()
        and feature_rows_path.read_bytes() == rows_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(feature_rows_path, rows_payload)
        _atomic_write(manifest_path, manifest_payload)

    return FeatureMaterializationResult(
        feature_rows_path=feature_rows_path,
        manifest_path=manifest_path,
        feature_row_count=len(rows),
        features_sha256=_sha256(rows_payload),
        status="already_current" if is_current else "written",
    )


def _canonical_inputs(
    fixtures_path: Path,
    canonical_manifest_path: Path,
    entry: HistoricalFile,
    *,
    source_id: str,
) -> tuple[
    tuple[Fixture, ...],
    _CanonicalDatasetManifest,
    CanonicalDatasetProvenance,
]:
    fixture_payload = fixtures_path.read_bytes()
    canonical_manifest = _CanonicalDatasetManifest.model_validate_json(
        canonical_manifest_path.read_text(encoding="utf-8")
    )
    if _sha256(fixture_payload) != canonical_manifest.fixtures_sha256:
        msg = "canonical fixture checksum does not match its dataset manifest"
        raise FeatureDatasetError(msg)
    if canonical_manifest.source.file_id != entry.id:
        msg = "canonical dataset references a different raw artifact"
        raise FeatureDatasetError(msg)
    if (
        canonical_manifest.source.sha256 != entry.sha256
        or canonical_manifest.source.captured_at != entry.captured_at
    ):
        msg = "canonical dataset raw-source lineage does not match the manifest"
        raise FeatureDatasetError(msg)

    fixtures = tuple(
        Fixture.model_validate_json(line)
        for line in fixture_payload.decode().splitlines()
    )
    if len(fixtures) != canonical_manifest.fixture_count:
        msg = "canonical fixture count does not match its dataset manifest"
        raise FeatureDatasetError(msg)
    provenance = CanonicalDatasetProvenance(
        dataset_id=canonical_manifest.dataset_id,
        dataset_schema_version=canonical_manifest.dataset_schema_version,
        competition_id=canonical_manifest.competition_id,
        season_id=canonical_manifest.season_id,
        fixtures_sha256=canonical_manifest.fixtures_sha256,
        team_registry_schema_version=(canonical_manifest.team_registry_schema_version),
        season_registry_schema_version=(
            canonical_manifest.season_registry_schema_version
        ),
        source=SourceArtifactProvenance(
            source_id=source_id,
            artifact_id=entry.id,
            sha256=entry.sha256,
            captured_at=entry.captured_at,
        ),
    )
    return fixtures, canonical_manifest, provenance


def materialize_feature_entry(
    manifest_path: Path,
    entry_id: str,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> FeatureMaterializationResult:
    """Verify raw and canonical data before building one season's features."""

    canonical_result = materialize_historical_entry(
        manifest_path,
        entry_id,
        team_registry_path,
        season_registry_path,
        data_root,
    )
    manifest = load_manifest(manifest_path)
    entry = manifest.get_file(entry_id)
    teams = load_team_registry(team_registry_path)
    seasons = load_season_registry(season_registry_path, teams)
    season_id = f"{entry.season_start:04d}-{entry.season_end:04d}"
    season = seasons.get(season_id)
    fixtures, canonical_manifest, provenance = _canonical_inputs(
        canonical_result.fixtures_path,
        canonical_result.manifest_path,
        entry,
        source_id=manifest.source.id,
    )
    if canonical_manifest.competition_id != season.competition_id:
        msg = "canonical dataset competition does not match the season registry"
        raise FeatureDatasetError(msg)
    if canonical_manifest.season_id != season.id:
        msg = "canonical dataset season does not match the season registry"
        raise FeatureDatasetError(msg)
    if canonical_manifest.team_registry_schema_version != teams.schema_version:
        msg = "canonical dataset team-registry lineage is stale"
        raise FeatureDatasetError(msg)
    if canonical_manifest.season_registry_schema_version != seasons.schema_version:
        msg = "canonical dataset season-registry lineage is stale"
        raise FeatureDatasetError(msg)

    rows = build_point_in_time_feature_rows(fixtures, season, provenance)
    output_directory = data_root / "processed" / "features" / "epl" / season_id
    return write_feature_dataset(
        rows,
        output_directory,
        provenance,
        source_fixture_count=canonical_manifest.fixture_count,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize deterministic point-in-time feature datasets."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--entry-id")
    selection.add_argument(
        "--all",
        action="store_true",
        help="materialize every manifest entry in manifest order",
    )
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--seasons", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        entry_ids = (
            tuple(entry.id for entry in load_manifest(arguments.manifest).files)
            if arguments.all
            else (arguments.entry_id,)
        )
        results = tuple(
            materialize_feature_entry(
                arguments.manifest,
                entry_id,
                arguments.teams,
                arguments.seasons,
                arguments.data_root,
            )
            for entry_id in entry_ids
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    serialized_results = []
    for result in results:
        serialized = asdict(result)
        serialized["feature_rows_path"] = str(result.feature_rows_path)
        serialized["manifest_path"] = str(result.manifest_path)
        serialized_results.append(serialized)
    final_output: object = (
        serialized_results if arguments.all else serialized_results[0]
    )
    print(json.dumps(final_output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
