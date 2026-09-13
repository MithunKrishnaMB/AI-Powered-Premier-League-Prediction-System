"""Unit contracts for immutable PostgreSQL aggregate write plans."""

import hashlib
import json
from pathlib import Path

import pytest

from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    FilesystemRawManifestVerifier,
    ImmutableRow,
    PersistenceTable,
    RawManifestVerificationError,
    RepositoryContractError,
    StoredObject,
)


def _canonical_object(payload: bytes = b'{"a":1,"b":2}\n') -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id="repository-test-json",
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
    )


def test_stored_object_preserves_exact_bytes_and_checksum() -> None:
    item = _canonical_object()

    assert item.payload == b'{"a":1,"b":2}\n'
    assert item.sha256 == hashlib.sha256(item.payload).hexdigest()


@pytest.mark.parametrize(
    "payload",
    (
        b'{"b":2,"a":1}\n',
        b'{"a":NaN}\n',
        b'{"a":1}\r\n',
        b'\xef\xbb\xbf{"a":1}\n',
    ),
)
def test_stored_object_rejects_noncanonical_json(payload: bytes) -> None:
    with pytest.raises(RepositoryContractError):
        _canonical_object(payload)


def test_json_lines_and_numpy_profiles_remain_distinct() -> None:
    jsonl = StoredObject.from_bytes(
        b'{"a":1}\n{"b":2}\n',
        media_type="application/x-ndjson",
        encoding="utf-8",
        format_id="rows-jsonl",
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSONL,
    )
    numpy = StoredObject.from_bytes(
        b"NUMPY",
        media_type="application/x-npy",
        encoding=None,
        format_id="numpy-array-v1",
        canonicalization_profile=CanonicalizationProfile.NUMPY_ARRAY,
    )

    assert jsonl.canonicalization_profile is CanonicalizationProfile.CANONICAL_JSONL
    assert numpy.canonicalization_profile is CanonicalizationProfile.NUMPY_ARRAY


def test_expected_checksum_must_match_before_database_access() -> None:
    with pytest.raises(RepositoryContractError, match="checksum"):
        StoredObject.from_bytes(
            b'{"a":1}\n',
            media_type="application/json",
            encoding="utf-8",
            format_id="repository-test-json",
            canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
            expected_sha256="0" * 64,
        )


def test_row_identity_and_dependency_order_fail_closed() -> None:
    competition = ImmutableRow.build(
        PersistenceTable.COMPETITION,
        {
            "competition_id": "test",
            "display_name": "Test",
            "country_code": "TST",
            "timezone_name": "UTC",
        },
        identity_columns=("competition_id",),
    )
    source = ImmutableRow.build(
        PersistenceTable.SOURCE,
        {
            "source_id": "source",
            "provider_name": "Source",
            "homepage_url": "https://example.test",
            "attribution": "Test",
            "usage_notice": "Test",
        },
        identity_columns=("source_id",),
    )

    with pytest.raises(RepositoryContractError, match="dependency order"):
        AggregateWritePlan(
            kind=AggregateKind.IDENTITY_REFERENCE,
            identity="reversed",
            rows=(source, competition),
        )
    with pytest.raises(RepositoryContractError, match="absent"):
        ImmutableRow.build(
            PersistenceTable.COMPETITION,
            {"competition_id": "test"},
            identity_columns=("missing_id",),
        )
    with pytest.raises(RepositoryContractError, match="aggregate boundary"):
        AggregateWritePlan(
            kind=AggregateKind.EXACT_OBJECT,
            identity="wrong-boundary",
            rows=(competition,),
        )


def test_filesystem_verifier_checks_every_raw_capture_before_returning(
    tmp_path: Path,
) -> None:
    raw = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,01/01/2025,Home,Away,1,0,H\n"
    destination = tmp_path / "raw" / "fixture.csv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(raw)
    manifest_payload = {
        "schema_version": 1,
        "source": {
            "id": "test-source",
            "name": "Test",
            "homepage_url": "https://example.test",
            "allowed_hosts": ["example.test"],
            "attribution": "Test",
            "usage_notice": "Test",
        },
        "files": [
            {
                "id": "test-2024-2025",
                "competition_code": "E0",
                "competition_name": "Test",
                "country": "England",
                "season_start": 2024,
                "season_end": 2025,
                "url": "https://example.test/fixture.csv",
                "destination": "raw/fixture.csv",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "expected_bytes": len(raw),
                "expected_rows": 1,
                "required_columns": [
                    "Div",
                    "Date",
                    "HomeTeam",
                    "AwayTeam",
                    "FTHG",
                    "FTAG",
                    "FTR",
                ],
                "encoding": "utf-8",
                "captured_at": "2026-09-13T00:00:00Z",
                "immutable": True,
            }
        ],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    evidence = FilesystemRawManifestVerifier(manifest, tmp_path).verify()

    assert evidence.verified_artifact_ids == ("test-2024-2025",)
    assert evidence.manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()

    destination.write_bytes(b"changed")
    with pytest.raises(RawManifestVerificationError):
        FilesystemRawManifestVerifier(manifest, tmp_path).verify()
