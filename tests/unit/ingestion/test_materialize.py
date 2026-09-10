"""Tests for deterministic canonical dataset materialization."""

import hashlib
import json
from pathlib import Path

import pytest

import pl_platform.ingestion.materialize as materialize_module
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonRegistry,
    load_season_registry,
)
from pl_platform.domain.teams import TeamRegistry, load_team_registry
from pl_platform.ingestion.manifest import HistoricalFile, load_manifest
from pl_platform.ingestion.materialize import (
    MaterializationResult,
    main,
    write_canonical_dataset,
)
from pl_platform.quality.fixtures import DataQualityError
from tests.unit.quality.test_fixtures import complete_fixtures


def _inputs() -> tuple[
    TeamRegistry,
    SeasonRegistry,
    HistoricalFile,
    PremierLeagueSeason,
]:
    teams = load_team_registry(Path("data/reference/teams.json"))
    seasons = load_season_registry(Path("data/reference/seasons.json"), teams)
    source = load_manifest(Path("data/manifests/football-data.json")).get_file(
        "epl-2025-2026"
    )
    return teams, seasons, source, seasons.get("2025-2026")


def test_writes_deterministic_dataset_and_manifest(tmp_path: Path) -> None:
    teams, seasons, source, season = _inputs()
    fixtures = complete_fixtures()

    first = write_canonical_dataset(
        fixtures,
        tmp_path,
        source,
        season,
        team_registry_schema_version=teams.schema_version,
        season_registry_schema_version=seasons.schema_version,
    )
    original_bytes = first.fixtures_path.read_bytes()
    second = write_canonical_dataset(
        tuple(reversed(fixtures)),
        tmp_path,
        source,
        season,
        team_registry_schema_version=teams.schema_version,
        season_registry_schema_version=seasons.schema_version,
    )
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))

    assert first.status == "written"
    assert second.status == "already_current"
    assert second.fixtures_path.read_bytes() == original_bytes
    assert first.fixture_count == 380
    assert first.fixtures_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert manifest["source"]["sha256"] == source.sha256
    assert manifest["dataset_schema_version"] == 2


def test_replaces_stale_generated_output(tmp_path: Path) -> None:
    teams, seasons, source, season = _inputs()
    fixtures = complete_fixtures()
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "fixtures.jsonl").write_text("stale", encoding="utf-8")
    (tmp_path / "dataset-manifest.json").write_text("stale", encoding="utf-8")

    result = write_canonical_dataset(
        fixtures,
        tmp_path,
        source,
        season,
        team_registry_schema_version=teams.schema_version,
        season_registry_schema_version=seasons.schema_version,
    )

    assert result.status == "written"
    assert result.fixtures_path.read_text(encoding="utf-8") != "stale"
    assert not list(tmp_path.glob("*.tmp"))


def test_refuses_to_materialize_invalid_dataset(tmp_path: Path) -> None:
    teams, seasons, source, season = _inputs()

    with pytest.raises(DataQualityError, match="fixture_count"):
        write_canonical_dataset(
            complete_fixtures()[:-1],
            tmp_path,
            source,
            season,
            team_registry_schema_version=teams.schema_version,
            season_registry_schema_version=seasons.schema_version,
        )


def test_cli_prints_materialization_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = MaterializationResult(
        fixtures_path=tmp_path / "fixtures.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        fixture_count=380,
        fixtures_sha256="a" * 64,
        status="written",
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_historical_entry",
        lambda *args: expected,
    )

    exit_code = main(
        [
            "--manifest",
            "manifest.json",
            "--entry-id",
            "entry",
            "--teams",
            "teams.json",
            "--seasons",
            "seasons.json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["fixture_count"] == 380
    assert output["status"] == "written"


def test_cli_can_materialize_all_manifest_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = MaterializationResult(
        fixtures_path=tmp_path / "fixtures.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        fixture_count=380,
        fixtures_sha256="a" * 64,
        status="written",
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_historical_entry",
        lambda *args: expected,
    )

    exit_code = main(
        [
            "--manifest",
            "data/manifests/football-data.json",
            "--all",
            "--teams",
            "teams.json",
            "--seasons",
            "seasons.json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(output) == 11
    assert all(result["fixture_count"] == 380 for result in output)
