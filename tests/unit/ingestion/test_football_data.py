"""Tests for Football-Data source parsing."""

import hashlib
from datetime import date, time
from pathlib import Path

import pytest

from pl_platform.ingestion.football_data import (
    FootballDataResult,
    SourceParseError,
    parse_football_data_csv,
)
from pl_platform.ingestion.manifest import HistoricalDataManifest

HEADER = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
    "Referee,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,B365H\n"
)


def _payload(*rows: str, header: str = HEADER) -> bytes:
    return (header + "".join(f"{row}\n" for row in rows)).encode()


def _manifest(payload: bytes, expected_rows: int) -> HistoricalDataManifest:
    return HistoricalDataManifest.model_validate(
        {
            "schema_version": 1,
            "source": {
                "id": "football-data-uk",
                "name": "Football-Data",
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
                    "expected_rows": expected_rows,
                    "required_columns": ["Date"],
                    "encoding": "utf-8",
                    "captured_at": "2026-09-10T00:00:00Z",
                    "immutable": True,
                }
            ],
        }
    )


def _write_source(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / "E0.csv"
    path.write_bytes(payload)
    return path


def test_parses_typed_rows_and_retains_additional_fields(tmp_path: Path) -> None:
    payload = _payload(
        "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1,0,H,A Taylor,"
        "19,10,10,3,7,10,6,7,1,2,0,0,1.40",
        "E0,01/01/2026,15:00,Arsenal,Chelsea,1,1,D,,,,,,,,,,,,,,,,,2.00",
    )

    matches = parse_football_data_csv(
        _write_source(tmp_path, payload),
        _manifest(payload, 2),
        "epl-2025-2026",
    )

    first, second = matches
    assert first.match_date == date(2025, 8, 15)
    assert first.kickoff_time == time(20, 0)
    assert first.full_time_result == FootballDataResult.HOME
    assert first.home_shots == 19
    assert first.additional_fields == {"B365H": "1.40"}
    assert second.full_time_result == FootballDataResult.DRAW
    assert second.half_time_result is None
    assert second.referee is None


def test_supports_two_digit_historical_dates(tmp_path: Path) -> None:
    payload = _payload(
        "E0,15/08/25,20:00,Liverpool,Bournemouth,1,0,H,,,,,,,,,,,,,,,,,1.40"
    )

    (match,) = parse_football_data_csv(
        _write_source(tmp_path, payload),
        _manifest(payload, 1),
        "epl-2025-2026",
    )

    assert match.match_date == date(2025, 8, 15)


@pytest.mark.parametrize(
    "row",
    [
        "E0,bad-date,20:00,Liverpool,Bournemouth,1,0,H,,,,,,,,,,,,,,,,,1.40",
        "E0,15/08/2025,bad-time,Liverpool,Bournemouth,1,0,H,,,,,,,,,,,,,,,,,1.40",
        "E0,15/08/2025,20:00,Liverpool,Bournemouth,no,0,H,,,,,,,,,,,,,,,,,1.40",
        "E0,15/08/2025,20:00,Liverpool,Bournemouth,-1,0,A,,,,,,,,,,,,,,,,,1.40",
        "E0,15/08/2025,20:00,Liverpool,Bournemouth,1,0,D,,,,,,,,,,,,,,,,,1.40",
    ],
)
def test_rejects_invalid_source_values(tmp_path: Path, row: str) -> None:
    payload = _payload(row)

    with pytest.raises(SourceParseError):
        parse_football_data_csv(
            _write_source(tmp_path, payload),
            _manifest(payload, 1),
            "epl-2025-2026",
        )


def test_rejects_missing_required_column(tmp_path: Path) -> None:
    payload = _payload(
        "15/08/2025,20:00,Liverpool,Bournemouth,1,0,H",
        header="Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n",
    )

    with pytest.raises(SourceParseError, match="missing columns: Div"):
        parse_football_data_csv(
            _write_source(tmp_path, payload),
            _manifest(payload, 1),
            "epl-2025-2026",
        )


def test_accepts_missing_optional_columns_as_null(tmp_path: Path) -> None:
    payload = _payload(
        "E0,15/08/2025,Liverpool,Bournemouth,1,0,H",
        header="Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n",
    )

    (match,) = parse_football_data_csv(
        _write_source(tmp_path, payload),
        _manifest(payload, 1),
        "epl-2025-2026",
    )

    assert match.kickoff_time is None
    assert match.half_time_result is None
    assert match.referee is None
    assert match.home_shots is None
