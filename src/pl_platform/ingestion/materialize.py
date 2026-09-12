"""Materialize verified source rows as a deterministic canonical dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pl_platform.domain.fixtures import Fixture
from pl_platform.domain.seasons import PremierLeagueSeason, load_season_registry
from pl_platform.domain.teams import load_team_registry
from pl_platform.ingestion.football_data import parse_football_data_csv
from pl_platform.ingestion.manifest import HistoricalFile, load_manifest
from pl_platform.ingestion.normalize import canonicalize_football_data_match
from pl_platform.quality.fixtures import (
    DataQualityError,
    validate_premier_league_fixtures,
)

DATASET_SCHEMA_VERSION = 2
MaterializationStatus = Literal["written", "already_current"]


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    fixtures_path: Path
    manifest_path: Path
    fixture_count: int
    fixtures_sha256: str
    status: MaterializationStatus


def _stable_fixture_bytes(fixtures: tuple[Fixture, ...]) -> bytes:
    ordered = sorted(fixtures, key=lambda fixture: (fixture.kickoff_at, fixture.id))
    lines = (
        json.dumps(
            fixture.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for fixture in ordered
    )
    return ("\n".join(lines) + "\n").encode()


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


def _dataset_manifest(
    fixtures_payload: bytes,
    fixtures: tuple[Fixture, ...],
    source: HistoricalFile,
    season: PremierLeagueSeason,
    *,
    team_registry_schema_version: int,
    season_registry_schema_version: int,
) -> bytes:
    payload = {
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": f"canonical-fixtures-{season.id}",
        "competition_id": season.competition_id,
        "season_id": season.id,
        "fixture_count": len(fixtures),
        "fixtures_sha256": _sha256(fixtures_payload),
        "source": {
            "file_id": source.id,
            "sha256": source.sha256,
            "captured_at": source.captured_at.isoformat(),
        },
        "team_registry_schema_version": team_registry_schema_version,
        "season_registry_schema_version": season_registry_schema_version,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def write_canonical_dataset(
    fixtures: tuple[Fixture, ...],
    output_directory: Path,
    source: HistoricalFile,
    season: PremierLeagueSeason,
    *,
    team_registry_schema_version: int,
    season_registry_schema_version: int,
) -> MaterializationResult:
    """Validate and atomically write a deterministic canonical dataset."""

    quality_report = validate_premier_league_fixtures(fixtures, season)
    if not quality_report.is_valid:
        raise DataQualityError(quality_report)

    fixtures_payload = _stable_fixture_bytes(fixtures)
    manifest_payload = _dataset_manifest(
        fixtures_payload,
        fixtures,
        source,
        season,
        team_registry_schema_version=team_registry_schema_version,
        season_registry_schema_version=season_registry_schema_version,
    )
    fixtures_path = output_directory / "fixtures.jsonl"
    manifest_path = output_directory / "dataset-manifest.json"

    is_current = (
        fixtures_path.exists()
        and manifest_path.exists()
        and fixtures_path.read_bytes() == fixtures_payload
        and manifest_path.read_bytes() == manifest_payload
    )
    if not is_current:
        _atomic_write(fixtures_path, fixtures_payload)
        _atomic_write(manifest_path, manifest_payload)

    return MaterializationResult(
        fixtures_path=fixtures_path,
        manifest_path=manifest_path,
        fixture_count=len(fixtures),
        fixtures_sha256=_sha256(fixtures_payload),
        status="already_current" if is_current else "written",
    )


def materialize_historical_entry(
    manifest_path: Path,
    entry_id: str,
    team_registry_path: Path,
    season_registry_path: Path,
    data_root: Path,
) -> MaterializationResult:
    """Run verification, parsing, canonicalization, quality and writing."""

    manifest = load_manifest(manifest_path)
    entry = manifest.get_file(entry_id)
    relative_raw_path = PurePosixPath(entry.destination)
    raw_path = data_root.joinpath(*relative_raw_path.parts)
    teams = load_team_registry(team_registry_path)
    seasons = load_season_registry(season_registry_path, teams)
    season_id = f"{entry.season_start:04d}-{entry.season_end:04d}"
    season = seasons.get(season_id)
    source_matches = parse_football_data_csv(raw_path, manifest, entry_id)
    fixtures = tuple(
        canonicalize_football_data_match(match, teams) for match in source_matches
    )
    output_directory = data_root / "interim" / "canonical" / "epl" / season_id
    return write_canonical_dataset(
        fixtures,
        output_directory,
        entry,
        season,
        team_registry_schema_version=teams.schema_version,
        season_registry_schema_version=seasons.schema_version,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize canonical historical fixture datasets."
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
            materialize_historical_entry(
                arguments.manifest,
                entry_id,
                arguments.teams,
                arguments.seasons,
                arguments.data_root,
            )
            for entry_id in entry_ids
        )
    except (DataQualityError, KeyError, OSError, ValueError) as exc:
        parser.error(str(exc))

    serialized_results = []
    for result in results:
        serialized = asdict(result)
        serialized["fixtures_path"] = str(result.fixtures_path)
        serialized["manifest_path"] = str(result.manifest_path)
        serialized_results.append(serialized)
    final_output: object = (
        serialized_results if arguments.all else serialized_results[0]
    )
    print(json.dumps(final_output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
