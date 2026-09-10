"""Tests for checksum-verified immutable historical downloads."""

import hashlib
import json
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.error import URLError

import pytest

import pl_platform.ingestion.download as download_module
from pl_platform.ingestion.download import (
    ChecksumMismatchError,
    DownloadValidationError,
    ImmutableFileConflictError,
    download_manifest_entry,
    main,
)
from pl_platform.ingestion.manifest import HistoricalDataManifest

CSV_PAYLOAD = (
    b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
    b"E0,16/08/25,Liverpool,Bournemouth,4,2,H\n"
)


def _manifest(
    payload: bytes = CSV_PAYLOAD,
    *,
    required_columns: list[str] | None = None,
) -> HistoricalDataManifest:
    return HistoricalDataManifest.model_validate(
        {
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
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "expected_bytes": len(payload),
                    "expected_rows": 1,
                    "required_columns": required_columns
                    or ["Div", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"],
                    "encoding": "utf-8",
                    "captured_at": "2026-09-10T00:00:00Z",
                    "immutable": True,
                }
            ],
        }
    )


def _fetch(payload: bytes = CSV_PAYLOAD) -> download_module.Fetcher:
    def fetch(url: str, timeout: float, maximum_bytes: int) -> bytes:
        assert url == "https://data.example.com/E0.csv"
        assert timeout > 0
        assert maximum_bytes > 0
        return payload

    return fetch


def test_downloads_verified_payload_atomically(tmp_path: Path) -> None:
    result = download_manifest_entry(
        _manifest(),
        "epl-2025-2026",
        tmp_path,
        fetch=_fetch(),
    )

    assert result.status == "downloaded"
    assert result.path.read_bytes() == CSV_PAYLOAD
    assert result.byte_count == len(CSV_PAYLOAD)
    assert result.row_count == 1
    assert not list(result.path.parent.glob("*.tmp"))


def test_matching_existing_file_is_idempotent(tmp_path: Path) -> None:
    manifest = _manifest()
    first = download_manifest_entry(
        manifest,
        "epl-2025-2026",
        tmp_path,
        fetch=_fetch(),
    )

    def fail_if_called(url: str, timeout: float, maximum_bytes: int) -> bytes:
        pytest.fail(f"unexpected fetch: {url}, {timeout}, {maximum_bytes}")

    second = download_manifest_entry(
        manifest,
        "epl-2025-2026",
        tmp_path,
        fetch=fail_if_called,
    )

    assert second.status == "already_present"
    assert second.path == first.path


def test_refuses_to_overwrite_different_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "raw/test/E0.csv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"different")

    with pytest.raises(ImmutableFileConflictError, match="refusing to overwrite"):
        download_manifest_entry(
            _manifest(),
            "epl-2025-2026",
            tmp_path,
            fetch=_fetch(),
        )

    assert destination.read_bytes() == b"different"


def test_rejects_checksum_mismatch_without_publishing(tmp_path: Path) -> None:
    manifest = _manifest()
    changed_payload = CSV_PAYLOAD + b"x"

    with pytest.raises(DownloadValidationError, match="byte count mismatch"):
        download_manifest_entry(
            manifest,
            "epl-2025-2026",
            tmp_path,
            fetch=_fetch(changed_payload),
        )

    assert not (tmp_path / "raw/test/E0.csv").exists()


def test_rejects_same_size_checksum_mismatch(tmp_path: Path) -> None:
    changed_payload = CSV_PAYLOAD.replace(b"4,2,H", b"3,2,H")

    with pytest.raises(ChecksumMismatchError, match="checksum mismatch"):
        download_manifest_entry(
            _manifest(),
            "epl-2025-2026",
            tmp_path,
            fetch=_fetch(changed_payload),
        )


def test_rejects_missing_required_column(tmp_path: Path) -> None:
    manifest = _manifest(required_columns=["Div", "Referee"])

    with pytest.raises(DownloadValidationError, match="missing columns: Referee"):
        download_manifest_entry(
            manifest,
            "epl-2025-2026",
            tmp_path,
            fetch=_fetch(),
        )


def test_rejects_wrong_row_count(tmp_path: Path) -> None:
    payload = CSV_PAYLOAD + b"E0,17/08/25,Team A,Team B,1,1,D\n"
    manifest = _manifest(payload)

    manifest_payload = manifest.model_dump(mode="json")
    files = manifest_payload["files"]
    assert isinstance(files, list)
    files[0]["expected_rows"] = 1
    manifest = HistoricalDataManifest.model_validate(manifest_payload)

    with pytest.raises(DownloadValidationError, match="row count mismatch"):
        download_manifest_entry(
            manifest,
            "epl-2025-2026",
            tmp_path,
            fetch=_fetch(payload),
        )


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


def test_fetch_url_limits_response_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        download_module,
        "urlopen",
        lambda request, timeout: _FakeResponse(b"too large"),
    )

    with pytest.raises(DownloadValidationError, match="exceeded"):
        download_module._fetch_url("https://data.example.com/E0.csv", 1.0, 3)


def test_fetch_url_wraps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: object, timeout: float) -> _FakeResponse:
        raise URLError("offline")

    monkeypatch.setattr(download_module, "urlopen", fail)

    with pytest.raises(download_module.DownloadError, match="offline"):
        download_module._fetch_url("https://data.example.com/E0.csv", 1.0, 3)


def test_cli_prints_machine_readable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        _manifest().model_dump_json(indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(download_module, "_fetch_url", _fetch())

    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--entry-id",
            "epl-2025-2026",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "downloaded"
    assert output["row_count"] == 1
