"""Immutable PostgreSQL cache projection for exact current-provider responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError

from pl_platform.ingestion.current import (
    PROVIDER_CACHE_CAPABILITY_BY_OPERATION,
    CurrentProviderCapability,
    ExactProviderResponse,
    ProviderRequestIdentity,
    ProviderResponseCapture,
    deterministic_provider_cache_key,
)
from pl_platform.persistence.repositories import (
    MIGRATION_HEAD,
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    ImmutableRow,
    PersistenceFailureCategory,
    PersistenceResult,
    PersistenceTable,
    PostgresAggregateRepository,
    RawManifestVerifier,
    RepositoryError,
    StoredObject,
)


def _must_be_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class ProviderCacheEntry:
    cache_key_sha256: str
    source_id: str
    capability: CurrentProviderCapability
    request_identity: ProviderRequestIdentity
    response: ExactProviderResponse
    fetched_at: datetime
    expires_at: datetime
    compatibility_format_id: str

    def __post_init__(self) -> None:
        _must_be_utc(self.fetched_at, "fetched_at")
        _must_be_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.fetched_at:
            raise ValueError("provider cache expiry must follow retrieval")
        expected_key = deterministic_provider_cache_key(
            source_id=self.source_id,
            capability=self.capability,
            request_identity_sha256=self.request_identity.sha256,
            fetched_at=self.fetched_at,
        )
        if self.cache_key_sha256 != expected_key:
            raise ValueError("provider cache key does not match its content identity")
        identity = json.loads(self.request_identity.payload.decode("utf-8"))
        if identity.get("capability") != self.capability.value:
            raise ValueError("cached request capability does not match lookup")
        scope = identity.get("scope")
        provider_competition = (
            scope.get("provider_competition_id") if isinstance(scope, dict) else None
        )
        identity_source = (
            provider_competition.get("source_id")
            if isinstance(provider_competition, dict)
            else None
        )
        if identity_source != self.source_id:
            raise ValueError("cached request source does not match lookup")
        compatibility = identity.get("compatibility")
        if not isinstance(compatibility, dict):
            raise ValueError("cached request has no compatibility metadata")
        expected_format = (
            f"current-provider-v{compatibility.get('contract_version')}."
            f"{compatibility.get('provider_api_version')}."
            f"{compatibility.get('parser_schema_version')}"
        )
        if self.compatibility_format_id != expected_format:
            raise ValueError("cached response compatibility does not match request")

    def is_fresh_at(self, value: datetime) -> bool:
        _must_be_utc(value, "cache lookup time")
        return self.fetched_at <= value < self.expires_at


def provider_cache_write_plan(
    capture: ProviderResponseCapture,
    *,
    expires_at: datetime,
) -> AggregateWritePlan:
    """Project exact request/response bytes into the existing immutable schema."""

    _must_be_utc(expires_at, "expires_at")
    if expires_at <= capture.retrieved_at:
        raise ValueError("provider cache expiry must follow retrieval")
    cache_key = deterministic_provider_cache_key(
        source_id=capture.source_id,
        capability=capture.capability,
        request_identity_sha256=capture.request_identity.sha256,
        fetched_at=capture.retrieved_at,
    )
    request_object = StoredObject.from_bytes(
        capture.request_identity.payload,
        media_type="application/json",
        encoding="utf-8",
        format_id="current-provider-request-v1",
        canonicalization_profile=CanonicalizationProfile.IDENTITY_JSON,
        expected_sha256=capture.request_identity.sha256,
    )
    response_object = StoredObject.from_bytes(
        capture.response.body,
        media_type=capture.response.media_type,
        encoding=capture.response.encoding,
        format_id=capture.compatibility.format_id,
        canonicalization_profile=CanonicalizationProfile.OPAQUE,
        expected_sha256=capture.response.sha256,
    )
    row = ImmutableRow.build(
        PersistenceTable.PROVIDER_RESPONSE,
        {
            "cache_key_sha256": cache_key,
            "source_id": capture.source_id,
            "capability": capture.cache_capability.value,
            "request_identity_sha256": capture.request_identity.sha256,
            "response_sha256": capture.response.sha256,
            "fetched_at": capture.retrieved_at,
            "expires_at": expires_at,
            "http_status": capture.response.http_status,
            "media_type": capture.response.media_type,
            "etag": capture.response.etag,
            "last_modified": capture.response.last_modified,
        },
        identity_columns=("cache_key_sha256",),
    )
    return AggregateWritePlan(
        kind=AggregateKind.PROVIDER_CACHE,
        identity=cache_key,
        objects=(request_object, response_object),
        rows=(row,),
    )


class ProviderCacheRepository:
    """Store and retrieve immutable exact provider responses."""

    def __init__(
        self,
        engine: Engine,
        raw_manifest_verifier: RawManifestVerifier,
    ) -> None:
        self._engine = engine
        self._aggregate_repository = PostgresAggregateRepository(
            engine,
            raw_manifest_verifier,
        )

    def store(
        self,
        capture: ProviderResponseCapture,
        *,
        expires_at: datetime,
    ) -> PersistenceResult:
        return self._aggregate_repository.persist(
            provider_cache_write_plan(capture, expires_at=expires_at)
        )

    def get_latest_fresh(
        self,
        *,
        source_id: str,
        capability: CurrentProviderCapability,
        request_identity_sha256: str,
        at: datetime,
    ) -> ProviderCacheEntry | None:
        """Return the latest unexpired exact response for one exact request."""

        _must_be_utc(at, "cache lookup time")
        if len(request_identity_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in request_identity_sha256
        ):
            raise ValueError("request identity must be lowercase SHA-256")
        cache_capability = PROVIDER_CACHE_CAPABILITY_BY_OPERATION[capability]
        try:
            with self._engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar_one_or_none()
                if revision != MIGRATION_HEAD:
                    raise RepositoryError(
                        PersistenceFailureCategory.SCHEMA_VERSION_INCOMPATIBLE,
                        AggregateKind.PROVIDER_CACHE,
                    )
                row = (
                    connection.execute(
                        text(
                            "SELECT r.cache_key_sha256, r.source_id, r.capability, "
                            "r.request_identity_sha256, r.response_sha256, "
                            "r.fetched_at, r.expires_at, r.http_status, "
                            "r.media_type, r.etag, r.last_modified, "
                            "request_object.payload AS request_payload, "
                            "response_object.payload AS response_payload, "
                            "response_object.media_type AS response_object_media_type, "
                            "response_object.encoding AS response_encoding, "
                            "response_object.format_id AS response_format_id "
                            "FROM provider_cache.response AS r "
                            "JOIN lineage.stored_object AS request_object "
                            "ON request_object.sha256 = r.request_identity_sha256 "
                            "JOIN lineage.stored_object AS response_object "
                            "ON response_object.sha256 = r.response_sha256 "
                            "WHERE r.source_id = :source_id "
                            "AND r.capability = :capability "
                            "AND r.request_identity_sha256 = :request_sha256 "
                            "AND r.fetched_at <= :at AND r.expires_at > :at "
                            "ORDER BY r.fetched_at DESC, r.cache_key_sha256 DESC "
                            "LIMIT 1"
                        ),
                        {
                            "source_id": source_id,
                            "capability": cache_capability.value,
                            "request_sha256": request_identity_sha256,
                            "at": at,
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
        except RepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise RepositoryError(
                PersistenceFailureCategory.DATABASE_OPERATION_FAILED,
                AggregateKind.PROVIDER_CACHE,
            ) from exc
        if row is None:
            return None
        return self._entry_from_row(row, capability)

    @staticmethod
    def _entry_from_row(
        row: RowMapping,
        capability: CurrentProviderCapability,
    ) -> ProviderCacheEntry:
        values = dict(row)
        request_payload = bytes(cast(bytes | memoryview, values["request_payload"]))
        response_payload = bytes(cast(bytes | memoryview, values["response_payload"]))
        if values["response_object_media_type"] != values["media_type"]:
            raise ValueError("cached response media metadata does not reconcile")
        request_identity = ProviderRequestIdentity(
            payload=request_payload,
            sha256=str(values["request_identity_sha256"]),
        )
        response = ExactProviderResponse.model_validate(
            {
                "body": response_payload,
                "sha256": str(values["response_sha256"]),
                "http_status": values["http_status"],
                "media_type": values["media_type"],
                "encoding": values["response_encoding"],
                "etag": values["etag"],
                "last_modified": values["last_modified"],
            }
        )
        return ProviderCacheEntry(
            cache_key_sha256=str(values["cache_key_sha256"]),
            source_id=str(values["source_id"]),
            capability=capability,
            request_identity=request_identity,
            response=response,
            fetched_at=cast(datetime, values["fetched_at"]),
            expires_at=cast(datetime, values["expires_at"]),
            compatibility_format_id=str(values["response_format_id"]),
        )
