"""Transactional PostgreSQL repository tests through Step 6.8."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from pl_platform.core.config import Settings
from pl_platform.domain.current import (
    CurrentSeasonScope,
    ProviderCompetitionIdentifier,
    ProviderSeasonIdentifier,
)
from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentSeasonFixturesRequest,
    ExactProviderResponse,
    PageMetadata,
    ProviderCompatibility,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    provider_request_identity,
)
from pl_platform.persistence.database import create_database_engine
from pl_platform.persistence.post_match_workflow import PostMatchWorkflowRepository
from pl_platform.persistence.provider_cache import (
    ProviderCacheLookupStatus,
    ProviderCacheRepository,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    FilesystemRawManifestVerifier,
    ImmutableRow,
    PersistenceFailureCategory,
    PersistenceTable,
    PostgresAggregateRepository,
    RawManifestEvidence,
    RawManifestVerificationError,
    RepositoryError,
    StoredObject,
)
from pl_platform.prediction import (
    PostMatchWorkflow,
    WorkflowChildReference,
    next_post_match_workflow_event,
    post_match_workflow_identity,
)

SOURCE = "current-cache-test-provider"
NOW = datetime(2026, 9, 14, 10, tzinfo=UTC)


def _current_capture() -> ProviderResponseCapture:
    compatibility = ProviderCompatibility(
        provider_api_version="api-v1",
        parser_schema_version="parser-v1",
    )
    scope = CurrentSeasonScope(
        competition_id="eng-premier-league",
        season_id="2026-2027",
        provider_competition_id=ProviderCompetitionIdentifier(
            source_id=SOURCE,
            external_id="PL",
        ),
        provider_season_id=ProviderSeasonIdentifier(
            source_id=SOURCE,
            external_id="2026",
        ),
    )
    request = CurrentSeasonFixturesRequest(
        scope=scope,
        compatibility=compatibility,
    )
    body = b'{"ok":true}\n'
    return ProviderResponseCapture(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity=provider_request_identity(request),
        retrieved_at=NOW,
        provider_generated_at=NOW - timedelta(seconds=1),
        compatibility=compatibility,
        page=PageMetadata(returned_count=0, has_more=False),
        quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
        response=ExactProviderResponse(
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        ),
    )


@pytest.fixture(scope="module")
def test_engine() -> Iterator[Engine]:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.skip("test PostgreSQL URL is not configured")
    engine = create_database_engine(settings, target="test")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if revision != "f0009_step_7_9":
        engine.dispose()
        pytest.skip("test PostgreSQL database is not at the Step 6.8 head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def repository(test_engine: Engine) -> PostgresAggregateRepository:
    return PostgresAggregateRepository(
        test_engine,
        FilesystemRawManifestVerifier(
            manifest_path=Path("data/manifests/football-data.json"),
            data_root=Path("data"),
        ),
    )


def _object(payload: bytes) -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id="repository-contract-json",
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
    )


def _competition(country_code: str = "TST") -> ImmutableRow:
    return ImmutableRow.build(
        PersistenceTable.COMPETITION,
        {
            "competition_id": "repository-contract-test",
            "display_name": "Repository Contract Test",
            "country_code": country_code,
            "timezone_name": "UTC",
        },
        identity_columns=("competition_id",),
    )


@pytest.mark.postgresql
def test_atomic_repository_is_exact_and_idempotent(
    repository: PostgresAggregateRepository,
) -> None:
    plan = AggregateWritePlan(
        kind=AggregateKind.IDENTITY_REFERENCE,
        identity="repository-contract-test",
        objects=(_object(b'{"repository_contract":1}\n'),),
        rows=(_competition(),),
    )

    first = repository.persist(plan)
    second = repository.persist(plan)

    assert first.inserted_objects + first.existing_objects == 1
    assert first.inserted_rows + first.existing_rows == 1
    assert second.inserted_objects == second.inserted_rows == 0
    assert second.existing_objects == second.existing_rows == 1
    loaded = repository.get(
        PersistenceTable.COMPETITION,
        {"competition_id": "repository-contract-test"},
    )
    assert loaded is not None
    assert loaded["country_code"] == "TST"


@pytest.mark.postgresql
def test_post_match_journal_append_and_retry_are_exact(
    repository: PostgresAggregateRepository,
) -> None:
    evaluations = (
        WorkflowChildReference(id=UUID(int=81001), identity_sha256="1" * 64),
    )
    advancement = WorkflowChildReference(id=UUID(int=81002), identity_sha256="2" * 64)
    predictions = (
        WorkflowChildReference(id=UUID(int=81003), identity_sha256="3" * 64),
    )
    simulation = WorkflowChildReference(id=UUID(int=81004), identity_sha256="4" * 64)
    workflow_id, checksum, _ = post_match_workflow_identity(
        season_id="2026-2027",
        evaluations=evaluations,
        advancement=advancement,
        prediction_regenerations=predictions,
        simulation_regeneration=simulation,
    )
    workflow = PostMatchWorkflow(
        id=workflow_id,
        identity_sha256=checksum,
        season_id="2026-2027",
        evaluations=evaluations,
        advancement=advancement,
        prediction_regenerations=predictions,
        simulation_regeneration=simulation,
    )
    journal = PostMatchWorkflowRepository(repository)

    history = journal.create(workflow)
    while not history.is_complete:
        event = next_post_match_workflow_event(workflow, history.events[-1])
        history = journal.append(workflow, event)

    assert history.is_complete
    assert journal.create(workflow) == history


@pytest.mark.postgresql
def test_existing_identity_with_different_content_fails_closed(
    repository: PostgresAggregateRepository,
) -> None:
    original = _object(b'{"repository_contract":1}\n')
    conflicting = StoredObject(
        sha256=original.sha256,
        payload=original.payload,
        media_type=original.media_type,
        encoding=original.encoding,
        format_id="different-format-json",
        canonicalization_profile=original.canonicalization_profile,
    )
    plan = AggregateWritePlan(
        kind=AggregateKind.EXACT_OBJECT,
        identity="existing-object-conflict",
        objects=(conflicting,),
    )

    with pytest.raises(RepositoryError) as captured:
        repository.persist(plan)

    assert (
        captured.value.category is PersistenceFailureCategory.EXISTING_RECORD_CONFLICT
    )


@pytest.mark.postgresql
def test_constraint_failure_rolls_back_authoritative_bytes(
    repository: PostgresAggregateRepository,
    test_engine: Engine,
) -> None:
    item = _object(b'{"rollback_contract":1}\n')
    plan = AggregateWritePlan(
        kind=AggregateKind.IDENTITY_REFERENCE,
        identity="invalid-competition",
        objects=(item,),
        rows=(_competition(country_code="invalid"),),
    )

    with pytest.raises(RepositoryError) as captured:
        repository.persist(plan)

    assert (
        captured.value.category
        is PersistenceFailureCategory.DATABASE_CONSTRAINT_VIOLATION
    )
    with test_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM lineage.stored_object WHERE sha256 = :sha"),
            {"sha": item.sha256},
        ).scalar_one()
    assert count == 0


@pytest.mark.postgresql
def test_database_immutability_guard_rejects_update(test_engine: Engine) -> None:
    with pytest.raises(DBAPIError), test_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE identity.competition SET display_name = 'Changed' "
                "WHERE competition_id = 'repository-contract-test'"
            )
        )


@pytest.mark.postgresql
def test_database_checksum_constraint_fails_closed(test_engine: Engine) -> None:
    with pytest.raises(DBAPIError), test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO lineage.stored_object ("
                "sha256, byte_count, media_type, encoding, format_id, "
                "canonicalization_profile, payload) VALUES ("
                ":sha, 1, 'application/octet-stream', 'utf-8', "
                "'invalid-checksum-test', 'opaque', :payload)"
            ),
            {"sha": "0" * 64, "payload": b"x"},
        )


class _RejectingVerifier:
    def verify(self) -> RawManifestEvidence:
        raise RawManifestVerificationError("rejected")


@pytest.mark.postgresql
def test_raw_verification_failure_prevents_transaction(test_engine: Engine) -> None:
    repository = PostgresAggregateRepository(test_engine, _RejectingVerifier())
    item = _object(b'{"raw_gate":1}\n')
    plan = AggregateWritePlan(
        kind=AggregateKind.EXACT_OBJECT,
        identity="raw-gate",
        objects=(item,),
    )

    with pytest.raises(RepositoryError) as captured:
        repository.persist(plan)

    assert (
        captured.value.category
        is PersistenceFailureCategory.RAW_MANIFEST_VERIFICATION_FAILED
    )
    with test_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM lineage.stored_object WHERE sha256 = :sha"),
            {"sha": item.sha256},
        ).scalar_one()
    assert count == 0


@pytest.mark.postgresql
def test_verified_raw_lineage_must_match_before_transaction(
    repository: PostgresAggregateRepository,
    test_engine: Engine,
) -> None:
    item = _object(b'{"raw_lineage_gate":1}\n')
    plan = AggregateWritePlan(
        kind=AggregateKind.TRAINING,
        identity="raw-lineage-gate",
        objects=(item,),
        rows=(
            ImmutableRow.build(
                PersistenceTable.TRAINING_DATASET,
                {
                    "dataset_id": "raw-lineage-gate",
                    "historical_manifest_sha256": "0" * 64,
                },
                identity_columns=("dataset_id",),
            ),
        ),
    )

    with pytest.raises(RepositoryError) as captured:
        repository.persist(plan)

    assert captured.value.category is PersistenceFailureCategory.PROVENANCE_MISMATCH
    with test_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM lineage.stored_object WHERE sha256 = :sha"),
            {"sha": item.sha256},
        ).scalar_one()
    assert count == 0


@pytest.mark.postgresql
def test_provider_cache_round_trip_is_exact_fresh_and_idempotent(
    repository: PostgresAggregateRepository,
    test_engine: Engine,
) -> None:
    source = ImmutableRow.build(
        PersistenceTable.SOURCE,
        {
            "source_id": SOURCE,
            "provider_name": "Current Test Provider",
            "homepage_url": "https://api.example.test",
            "attribution": "Synthetic test provider",
            "usage_notice": "Tests only",
        },
        identity_columns=("source_id",),
    )
    repository.persist(
        AggregateWritePlan(
            kind=AggregateKind.IDENTITY_REFERENCE,
            identity=SOURCE,
            rows=(source,),
        )
    )
    cache = ProviderCacheRepository(
        test_engine,
        FilesystemRawManifestVerifier(
            manifest_path=Path("data/manifests/football-data.json"),
            data_root=Path("data"),
        ),
    )
    capture = _current_capture()
    expires_at = NOW + timedelta(minutes=5)

    first = cache.store(capture, expires_at=expires_at)
    second = cache.store(capture, expires_at=expires_at)
    loaded = cache.get_latest_fresh(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity_sha256=capture.request_identity.sha256,
        at=NOW + timedelta(minutes=1),
    )
    fresh = cache.lookup_latest(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity_sha256=capture.request_identity.sha256,
        at=NOW + timedelta(minutes=1),
    )
    stale = cache.lookup_latest(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity_sha256=capture.request_identity.sha256,
        at=expires_at,
    )
    missing = cache.lookup_latest(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity_sha256="0" * 64,
        at=NOW,
    )

    assert first.inserted_rows + first.existing_rows == 1
    assert second.inserted_objects == second.inserted_rows == 0
    assert loaded is not None
    assert loaded.response.body == capture.response.body
    assert loaded.response.sha256 == capture.response.sha256
    assert loaded.request_identity.payload == capture.request_identity.payload
    assert loaded.compatibility_format_id == capture.compatibility.format_id
    assert fresh.status is ProviderCacheLookupStatus.FRESH
    assert fresh.entry == loaded
    assert stale.status is ProviderCacheLookupStatus.STALE
    assert (
        stale.entry is not None and stale.entry.response.body == capture.response.body
    )
    assert missing.status is ProviderCacheLookupStatus.MISS
    assert missing.entry is None
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        cache.get_latest_fresh(
            source_id=SOURCE,
            capability=CurrentProviderCapability.FIXTURES,
            request_identity_sha256="invalid",
            at=NOW,
        )
    assert (
        cache.get_latest_fresh(
            source_id=SOURCE,
            capability=CurrentProviderCapability.FIXTURES,
            request_identity_sha256=capture.request_identity.sha256,
            at=expires_at,
        )
        is None
    )
