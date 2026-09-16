"""Exact-cache-aware completed-result retrieval and reconciliation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.ingestion.current import (
    CapabilityAvailability,
    CompletedResultsRequest,
    CompletedResultsResponse,
    CurrentProviderCapability,
    ProviderCapabilityManifest,
    ProviderResponseCapture,
    provider_request_identity,
)
from pl_platform.ingestion.current_transform import (
    CanonicalCompletedResult,
    CurrentTeamResolution,
    CurrentTransformationError,
    transform_completed_results,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheCompatibilityError,
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
)
from pl_platform.persistence.repositories import PersistenceResult


class FinalResultErrorCode(StrEnum):
    CACHE_INCOMPATIBLE = "cache_incompatible"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    CAPABILITY_TEMPORARILY_UNAVAILABLE = "capability_temporarily_unavailable"
    CAPABILITY_MANIFEST_INCOMPATIBLE = "capability_manifest_incompatible"
    RESPONSE_INCOMPATIBLE = "response_incompatible"
    PAGINATION_INCOMPATIBLE = "pagination_incompatible"
    CANONICALIZATION_FAILED = "canonicalization_failed"


class FinalResultReconciliationError(RuntimeError):
    def __init__(
        self,
        code: FinalResultErrorCode,
        safe_message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code.value)


class CompletedResultProvider(Protocol):
    def describe_capabilities(self) -> ProviderCapabilityManifest: ...

    def get_completed_results(
        self,
        request: CompletedResultsRequest,
    ) -> CompletedResultsResponse: ...


class CachedCompletedResultDecoder(Protocol):
    def decode_completed_results(
        self,
        *,
        request: CompletedResultsRequest,
        entry: ProviderCacheEntry,
    ) -> CompletedResultsResponse: ...


class CompletedResultCache(Protocol):
    def lookup_latest(
        self,
        *,
        source_id: str,
        capability: CurrentProviderCapability,
        request_identity_sha256: str,
        at: datetime,
    ) -> ProviderCacheLookup: ...

    def store(
        self,
        capture: ProviderResponseCapture,
        *,
        expires_at: datetime,
    ) -> object: ...


class CompletedResultRepository(Protocol):
    def reconcile_results(
        self,
        results: tuple[CanonicalCompletedResult, ...],
    ) -> PersistenceResult: ...


class FinalResultPageSource(StrEnum):
    FRESH_CACHE = "fresh_cache"
    CACHE_MISS_REFRESHED = "cache_miss_refreshed"
    STALE_CACHE_REFRESHED = "stale_cache_refreshed"


@dataclass(frozen=True, slots=True)
class FinalResultPageProvenance:
    source: FinalResultPageSource
    cache_key_sha256: str
    request_identity_sha256: str
    response_sha256: str
    retrieved_at: datetime
    expires_at: datetime
    compatibility_format_id: str


@dataclass(frozen=True, slots=True)
class FinalResultReconciliationResult:
    results: tuple[CanonicalCompletedResult, ...]
    pages: tuple[FinalResultPageProvenance, ...]
    persistence: PersistenceResult | None


class CacheAwareFinalResultReconciler:
    """Retrieve a complete result set before one immutable reconciliation."""

    def __init__(
        self,
        *,
        cache: CompletedResultCache,
        decoder: CachedCompletedResultDecoder,
        repository: CompletedResultRepository,
        provider: CompletedResultProvider | None,
        cache_ttl: timedelta,
    ) -> None:
        if cache_ttl <= timedelta(0):
            raise ValueError("completed-result cache TTL must be positive")
        self._cache = cache
        self._decoder = decoder
        self._repository = repository
        self._provider = provider
        self._cache_ttl = cache_ttl

    def reconcile(
        self,
        request: CompletedResultsRequest,
        *,
        resolution: CurrentTeamResolution,
        season: PremierLeagueSeason,
        at: datetime,
    ) -> FinalResultReconciliationResult:
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("result lookup time must be timezone-aware UTC")
        if request.page.cursor is not None:
            raise FinalResultReconciliationError(
                FinalResultErrorCode.PAGINATION_INCOMPATIBLE,
                "completed-result reconciliation must begin at the first page",
            )

        pages: list[FinalResultPageProvenance] = []
        results: list[CanonicalCompletedResult] = []
        provider_ids: set[str] = set()
        canonical_ids: set[UUID] = set()
        seen_cursors: set[str | None] = set()
        current_request = request
        manifest: ProviderCapabilityManifest | None = None
        while True:
            cursor = current_request.page.cursor
            if cursor in seen_cursors:
                raise FinalResultReconciliationError(
                    FinalResultErrorCode.PAGINATION_INCOMPATIBLE,
                    "completed-result pagination repeated a cursor",
                )
            seen_cursors.add(cursor)
            response, entry, source, manifest = self._read_page(
                current_request,
                at=at,
                manifest=manifest,
            )
            self._validate_response(current_request, response, entry)
            try:
                transformed = transform_completed_results(response, resolution, season)
            except CurrentTransformationError as exc:
                raise FinalResultReconciliationError(
                    FinalResultErrorCode.CANONICALIZATION_FAILED,
                    "completed results could not be mapped canonically",
                ) from exc
            self._extend_unique(
                results,
                transformed,
                provider_ids=provider_ids,
                canonical_ids=canonical_ids,
            )
            pages.append(self._provenance(entry, source))
            if not response.capture.page.has_more:
                break
            next_cursor = cast(str, response.capture.page.next_cursor)
            current_request = current_request.model_copy(
                update={
                    "page": current_request.page.model_copy(
                        update={"cursor": next_cursor}
                    )
                }
            )

        ordered = tuple(sorted(results, key=lambda item: item.fixture_id))
        persistence = self._repository.reconcile_results(ordered) if ordered else None
        return FinalResultReconciliationResult(
            results=ordered,
            pages=tuple(pages),
            persistence=persistence,
        )

    def _read_page(
        self,
        request: CompletedResultsRequest,
        *,
        at: datetime,
        manifest: ProviderCapabilityManifest | None,
    ) -> tuple[
        CompletedResultsResponse,
        ProviderCacheEntry,
        FinalResultPageSource,
        ProviderCapabilityManifest | None,
    ]:
        identity = provider_request_identity(request)
        try:
            lookup = self._cache.lookup_latest(
                source_id=request.scope.source_id,
                capability=CurrentProviderCapability.COMPLETED_RESULTS,
                request_identity_sha256=identity.sha256,
                at=at,
            )
        except ProviderCacheCompatibilityError as exc:
            raise FinalResultReconciliationError(
                FinalResultErrorCode.CACHE_INCOMPATIBLE,
                "cached completed-result response is incompatible",
            ) from exc
        if lookup.status is ProviderCacheLookupStatus.FRESH:
            entry = cast(ProviderCacheEntry, lookup.entry)
            try:
                response = self._decoder.decode_completed_results(
                    request=request,
                    entry=entry,
                )
            except (TypeError, ValueError) as exc:
                raise FinalResultReconciliationError(
                    FinalResultErrorCode.CACHE_INCOMPATIBLE,
                    "cached completed-result response could not be decoded",
                ) from exc
            return response, entry, FinalResultPageSource.FRESH_CACHE, manifest

        provider = self._require_provider()
        resolved_manifest = manifest or provider.describe_capabilities()
        self._require_supported(request, resolved_manifest)
        response = provider.get_completed_results(request)
        expires_at = response.capture.retrieved_at + self._cache_ttl
        entry = ProviderCacheEntry.from_capture(response.capture, expires_at=expires_at)
        self._validate_response(request, response, entry)
        self._cache.store(response.capture, expires_at=expires_at)
        source = (
            FinalResultPageSource.STALE_CACHE_REFRESHED
            if lookup.status is ProviderCacheLookupStatus.STALE
            else FinalResultPageSource.CACHE_MISS_REFRESHED
        )
        return response, entry, source, resolved_manifest

    def _require_provider(self) -> CompletedResultProvider:
        if self._provider is None:
            raise FinalResultReconciliationError(
                FinalResultErrorCode.PROVIDER_NOT_CONFIGURED,
                "no completed-result provider is configured",
            )
        return self._provider

    @staticmethod
    def _require_supported(
        request: CompletedResultsRequest,
        manifest: ProviderCapabilityManifest,
    ) -> None:
        if (
            manifest.source_id != request.scope.source_id
            or manifest.compatibility != request.compatibility
        ):
            raise FinalResultReconciliationError(
                FinalResultErrorCode.CAPABILITY_MANIFEST_INCOMPATIBLE,
                "provider capability metadata is incompatible with the request",
            )
        declaration = next(
            item
            for item in manifest.capabilities
            if item.capability is CurrentProviderCapability.COMPLETED_RESULTS
        )
        if declaration.availability is CapabilityAvailability.UNSUPPORTED:
            raise FinalResultReconciliationError(
                FinalResultErrorCode.CAPABILITY_UNSUPPORTED,
                "completed-result capability is unsupported",
            )
        if declaration.availability is CapabilityAvailability.TEMPORARILY_UNAVAILABLE:
            raise FinalResultReconciliationError(
                FinalResultErrorCode.CAPABILITY_TEMPORARILY_UNAVAILABLE,
                "completed-result capability is temporarily unavailable",
                retry_after_seconds=declaration.retry_after_seconds,
            )

    @staticmethod
    def _validate_response(
        request: CompletedResultsRequest,
        response: CompletedResultsResponse,
        entry: ProviderCacheEntry,
    ) -> None:
        identity = provider_request_identity(request)
        capture = response.capture
        if (
            response.scope != request.scope
            or capture.request_identity != identity
            or capture.request_identity != entry.request_identity
            or capture.response != entry.response
            or capture.retrieved_at != entry.fetched_at
            or capture.compatibility != request.compatibility
            or capture.compatibility.format_id != entry.compatibility_format_id
            or capture.page.request_cursor != request.page.cursor
        ):
            raise FinalResultReconciliationError(
                FinalResultErrorCode.RESPONSE_INCOMPATIBLE,
                "completed-result response provenance does not match its request",
            )

    @staticmethod
    def _extend_unique(
        target: list[CanonicalCompletedResult],
        results: Sequence[CanonicalCompletedResult],
        *,
        provider_ids: set[str],
        canonical_ids: set[UUID],
    ) -> None:
        for item in results:
            provider_id = item.observation.provider_fixture_id.external_id
            if provider_id in provider_ids or item.fixture_id in canonical_ids:
                raise FinalResultReconciliationError(
                    FinalResultErrorCode.PAGINATION_INCOMPATIBLE,
                    "completed-result pages contain duplicate identities",
                )
            provider_ids.add(provider_id)
            canonical_ids.add(item.fixture_id)
            target.append(item)

    @staticmethod
    def _provenance(
        entry: ProviderCacheEntry,
        source: FinalResultPageSource,
    ) -> FinalResultPageProvenance:
        return FinalResultPageProvenance(
            source=source,
            cache_key_sha256=entry.cache_key_sha256,
            request_identity_sha256=entry.request_identity.sha256,
            response_sha256=entry.response.sha256,
            retrieved_at=entry.fetched_at,
            expires_at=entry.expires_at,
            compatibility_format_id=entry.compatibility_format_id,
        )
