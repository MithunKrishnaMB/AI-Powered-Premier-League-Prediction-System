"""Transactional PostgreSQL repository tests for Steps 5.8 and 5.9."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from pl_platform.core.config import Settings
from pl_platform.persistence.database import create_database_engine
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
    if revision != "f0004_step_5_7":
        engine.dispose()
        pytest.skip("test PostgreSQL database is not at the Step 5.7 head")
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
