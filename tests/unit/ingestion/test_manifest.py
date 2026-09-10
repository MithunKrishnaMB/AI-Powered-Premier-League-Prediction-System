"""Tests for historical source manifest validation."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pl_platform.ingestion.manifest import HistoricalDataManifest, load_manifest


def _manifest_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "id": "source",
            "name": "Test source",
            "homepage_url": "https://data.example.com",
            "allowed_hosts": ["data.example.com"],
            "attribution": "Test data",
            "usage_notice": "Testing only",
        },
        "files": [
            {
                "id": "epl-2025-2026",
                "competition_code": "E0",
                "competition_name": "Premier League",
                "country": "England",
                "season_start": 2025,
                "season_end": 2026,
                "url": "https://data.example.com/E0.csv",
                "destination": "raw/test/E0.csv",
                "sha256": "0" * 64,
                "expected_bytes": 10,
                "expected_rows": 1,
                "required_columns": ["Div", "HomeTeam"],
                "encoding": "utf-8",
                "captured_at": "2026-09-10T00:00:00Z",
                "immutable": True,
            }
        ],
    }


def test_loads_repository_manifest() -> None:
    manifest = load_manifest(Path("data/manifests/football-data.json"))

    entry = manifest.get_file("epl-2025-2026")

    assert manifest.schema_version == 1
    assert entry.expected_rows == 380
    assert entry.sha256.endswith("07e62")


def test_load_manifest_reads_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

    manifest = load_manifest(manifest_path)

    assert manifest.source.id == "source"


def test_rejects_duplicate_entry_ids() -> None:
    payload = _manifest_payload()
    files = payload["files"]
    assert isinstance(files, list)
    files.append(files[0].copy())

    with pytest.raises(ValidationError, match="file IDs must be unique"):
        HistoricalDataManifest.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("destination", "../escape.csv", "relative CSV path"),
        ("url", "http://data.example.com/E0.csv", "must use HTTPS"),
        ("season_end", 2027, "exactly one year"),
    ],
)
def test_rejects_unsafe_or_inconsistent_file_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _manifest_payload()
    files = payload["files"]
    assert isinstance(files, list)
    files[0][field] = value

    with pytest.raises(ValidationError, match=message):
        HistoricalDataManifest.model_validate(payload)


def test_rejects_file_host_outside_source_allowlist() -> None:
    payload = _manifest_payload()
    files = payload["files"]
    assert isinstance(files, list)
    files[0]["url"] = "https://attacker.example/E0.csv"

    with pytest.raises(ValidationError, match="URL host is not allowed"):
        HistoricalDataManifest.model_validate(payload)


def test_missing_entry_has_descriptive_error() -> None:
    manifest = HistoricalDataManifest.model_validate(_manifest_payload())

    with pytest.raises(KeyError, match="missing"):
        manifest.get_file("missing")
