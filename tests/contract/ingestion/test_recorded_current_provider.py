"""Exact-byte offline tests for every current-provider capability."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from pl_platform.ingestion.current import CurrentProviderCapability
from pl_platform.ingestion.recorded import (
    RecordedResponseContractError,
    RecordedResponseManifest,
    RecordedResponseSpec,
    load_recorded_manifest,
    replay_recorded_response,
)
from tests.unit.ingestion.current_helpers import request_for

FIXTURE_ROOT = Path("tests/fixtures/current_provider")


def test_recorded_corpus_covers_and_replays_every_capability_exactly() -> None:
    manifest = load_recorded_manifest(FIXTURE_ROOT / "manifest.json")

    assert tuple(record.capability for record in manifest.recordings) == tuple(
        CurrentProviderCapability
    )
    for record in manifest.recordings:
        capture = replay_recorded_response(
            root=FIXTURE_ROOT,
            request=request_for(record.capability),
            spec=record,
        )
        decoded = json.loads(capture.response.body.decode(capture.response.encoding))

        assert (
            capture.response.body == (FIXTURE_ROOT / record.relative_path).read_bytes()
        )
        assert capture.response.sha256 == record.response_sha256
        assert decoded == {"operation": record.capability.value, "records": []}


def test_recorded_replay_rejects_checksum_and_request_identity_drift() -> None:
    record = load_recorded_manifest(FIXTURE_ROOT / "manifest.json").recordings[0]
    request = request_for(record.capability)

    with pytest.raises(RecordedResponseContractError, match="bytes or metadata"):
        replay_recorded_response(
            root=FIXTURE_ROOT,
            request=request,
            spec=record.model_copy(update={"response_sha256": "0" * 64}),
        )
    with pytest.raises(RecordedResponseContractError, match="request identity"):
        replay_recorded_response(
            root=FIXTURE_ROOT,
            request=request,
            spec=record.model_copy(update={"request_identity_sha256": "0" * 64}),
        )


def test_recorded_contract_rejects_unsafe_paths_and_incomplete_corpora() -> None:
    record = load_recorded_manifest(FIXTURE_ROOT / "manifest.json").recordings[0]

    with pytest.raises(ValidationError, match="safe relative POSIX"):
        RecordedResponseSpec.model_validate(
            {**record.model_dump(), "relative_path": "../teams.json"}
        )
    with pytest.raises(ValidationError, match="every capability"):
        RecordedResponseManifest(recordings=(record,))


def test_recorded_replay_rejects_mismatched_capability() -> None:
    record = load_recorded_manifest(FIXTURE_ROOT / "manifest.json").recordings[0]

    with pytest.raises(RecordedResponseContractError, match="capability"):
        replay_recorded_response(
            root=FIXTURE_ROOT,
            request=request_for(CurrentProviderCapability.FIXTURES),
            spec=record,
        )


def test_recorded_spec_rejects_unsafe_success_metadata() -> None:
    record = load_recorded_manifest(FIXTURE_ROOT / "manifest.json").recordings[0]
    payload = record.model_dump()

    for update, message in (
        ({"retrieved_at": datetime(2026, 9, 14, 10)}, "retrieval timestamp"),
        (
            {
                "provider_generated_at": datetime(2026, 9, 14, 10, tzinfo=UTC)
                + timedelta(seconds=1)
            },
            "cannot follow retrieval",
        ),
        ({"http_status": 503}, "successful HTTP status"),
    ):
        with pytest.raises(ValidationError, match=message):
            RecordedResponseSpec.model_validate({**payload, **update})


def test_recorded_replay_rejects_source_compatibility_and_missing_file() -> None:
    record = load_recorded_manifest(FIXTURE_ROOT / "manifest.json").recordings[0]
    request = request_for(record.capability)

    for changed, message in (
        (record.model_copy(update={"source_id": "another-source"}), "source"),
        (
            record.model_copy(
                update={
                    "compatibility": record.compatibility.model_copy(
                        update={"parser_schema_version": "parser-v2"}
                    )
                }
            ),
            "compatibility",
        ),
        (record.model_copy(update={"relative_path": "missing.json"}), "missing"),
    ):
        with pytest.raises(RecordedResponseContractError, match=message):
            replay_recorded_response(root=FIXTURE_ROOT, request=request, spec=changed)
