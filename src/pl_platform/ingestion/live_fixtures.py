"""Cache-aware provider-neutral current fixture reads."""

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
    CurrentProviderCapability,
    CurrentSeasonFixturesRequest,
    CurrentSeasonFixturesResponse,
    ProviderCapabilityManifest,
    ProviderResponseCapture,
    provider_request_identity,
)
from pl_platform.ingestion.current_transform import (
    CanonicalCurrentFixture,
    CurrentTeamResolution,
    CurrentTransformationError,
    transform_current_fixtures,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheCompatibilityError,
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
)


class LiveFixtureReadErrorCode(StrEnum):
    """Stable, provider-neutral failure categories for one live read."""

    CACHE_INCOMPATIBLE = "cache_incompatible"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    CAPABILITY_TEMPORARILY_UNAVAILABLE = "capability_temporarily_unavailable"
    CAPABILITY_MANIFEST_INCOMPATIBLE = "capability_manifest_incompatible"
    RESPONSE_INCOMPATIBLE = "response_incompatible"
    PAGINATION_INCOMPATIBLE = "pagination_incompatible"
    CANONICALIZATION_FAILED = "canonicalization_failed"


class LiveFixtureReadError(RuntimeError):
    """Sanitized failure raised by cache-aware fixture reads."""

    def __init__(
        self,
        code: LiveFixtureReadErrorCode,
        safe_message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code.value)


class LiveFixtureProvider(Protocol):
    """Minimal existing provider capability used by Step 9.1."""

    def describe_capabilities(self) -> ProviderCapabilityManifest: ...

    def get_current_season_fixtures(
        self,
        request: CurrentSeasonFixturesRequest,
    ) -> CurrentSeasonFixturesResponse: ...


class CachedFixtureResponseDecoder(Protocol):
    """Decode exact cached bytes under one pinned provider compatibility contract."""

    def decode_current_season_fixtures(
        self,
        *,
        request: CurrentSeasonFixturesRequest,
        entry: ProviderCacheEntry,
    ) -> CurrentSeasonFixturesResponse: ...


class ProviderCacheAccess(Protocol):
    """Narrow exact-cache port used by the live fixture reader."""

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


class LiveFixturePageSource(StrEnum):
    """How one exact provider page was satisfied."""

    FRESH_CACHE = "fresh_cache"
    CACHE_MISS_REFRESHED = "cache_miss_refreshed"
    STALE_CACHE_REFRESHED = "stale_cache_refreshed"


@dataclass(frozen=True, slots=True)
class LiveFixturePageProvenance:
    """Exact cache and retrieval evidence retained for one provider page."""

    source: LiveFixturePageSource
    cache_key_sha256: str
    request_identity_sha256: str
    response_sha256: str
    retrieved_at: datetime
    expires_at: datetime
    compatibility_format_id: str


@dataclass(frozen=True, slots=True)
class LiveFixtureReadResult:
    """Complete canonical fixture collection and ordered page provenance."""

    fixtures: tuple[CanonicalCurrentFixture, ...]
    pages: tuple[LiveFixturePageProvenance, ...]


class CacheAwareLiveFixtureReader:
    """Read complete current fixtures through exact cache and provider contracts."""

    def __init__(
        self,
        *,
        cache: ProviderCacheAccess,
        decoder: CachedFixtureResponseDecoder,
        provider: LiveFixtureProvider | None,
        cache_ttl: timedelta,
    ) -> None:
        if cache_ttl <= timedelta(0):
            raise ValueError("live fixture cache TTL must be positive")
        self._cache = cache
        self._decoder = decoder
        self._provider = provider
        self._cache_ttl = cache_ttl

    def read(
        self,
        request: CurrentSeasonFixturesRequest,
        *,
        resolution: CurrentTeamResolution,
        season: PremierLeagueSeason,
        at: datetime,
    ) -> LiveFixtureReadResult:
        """Read every provider page and return canonical fixtures only when complete."""

        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("live fixture lookup time must be timezone-aware UTC")
        if request.page.cursor is not None:
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE,
                "live fixture reads must begin at the first provider page",
            )

        pages: list[LiveFixturePageProvenance] = []
        fixtures: list[CanonicalCurrentFixture] = []
        provider_ids: set[str] = set()
        canonical_ids: set[UUID] = set()
        seen_cursors: set[str | None] = set()
        current_request = request
        manifest: ProviderCapabilityManifest | None = None

        while True:
            cursor = current_request.page.cursor
            if cursor in seen_cursors:
                raise LiveFixtureReadError(
                    LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE,
                    "provider pagination repeated a cursor",
                )
            seen_cursors.add(cursor)
            response, entry, source, manifest = self._read_page(
                current_request,
                at=at,
                manifest=manifest,
            )
            self._validate_response(current_request, response, entry)
            try:
                transformed = transform_current_fixtures(response, resolution, season)
            except CurrentTransformationError as exc:
                raise LiveFixtureReadError(
                    LiveFixtureReadErrorCode.CANONICALIZATION_FAILED,
                    "live fixture response could not be mapped canonically",
                ) from exc
            self._extend_unique(
                fixtures,
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

        return LiveFixtureReadResult(
            fixtures=tuple(
                sorted(
                    fixtures,
                    key=lambda item: (item.fixture.kickoff_at, item.fixture.id),
                )
            ),
            pages=tuple(pages),
        )

    def _read_page(
        self,
        request: CurrentSeasonFixturesRequest,
        *,
        at: datetime,
        manifest: ProviderCapabilityManifest | None,
    ) -> tuple[
        CurrentSeasonFixturesResponse,
        ProviderCacheEntry,
        LiveFixturePageSource,
        ProviderCapabilityManifest | None,
    ]:
        identity = provider_request_identity(request)
        try:
            lookup = self._cache.lookup_latest(
                source_id=request.scope.source_id,
                capability=CurrentProviderCapability.FIXTURES,
                request_identity_sha256=identity.sha256,
                at=at,
            )
        except ProviderCacheCompatibilityError as exc:
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.CACHE_INCOMPATIBLE,
                "cached fixture response is incompatible",
            ) from exc

        if lookup.status is ProviderCacheLookupStatus.FRESH:
            entry = cast(ProviderCacheEntry, lookup.entry)
            try:
                response = self._decoder.decode_current_season_fixtures(
                    request=request,
                    entry=entry,
                )
            except (TypeError, ValueError) as exc:
                raise LiveFixtureReadError(
                    LiveFixtureReadErrorCode.CACHE_INCOMPATIBLE,
                    "cached fixture response could not be decoded",
                ) from exc
            return (
                response,
                entry,
                LiveFixturePageSource.FRESH_CACHE,
                manifest,
            )

        provider = self._require_provider()
        resolved_manifest = manifest or provider.describe_capabilities()
        self._require_supported(request, resolved_manifest)
        response = provider.get_current_season_fixtures(request)
        expires_at = response.capture.retrieved_at + self._cache_ttl
        entry = ProviderCacheEntry.from_capture(
            response.capture,
            expires_at=expires_at,
        )
        self._validate_response(request, response, entry)
        self._cache.store(response.capture, expires_at=expires_at)
        source = (
            LiveFixturePageSource.STALE_CACHE_REFRESHED
            if lookup.status is ProviderCacheLookupStatus.STALE
            else LiveFixturePageSource.CACHE_MISS_REFRESHED
        )
        return response, entry, source, resolved_manifest

    def _require_provider(self) -> LiveFixtureProvider:
        if self._provider is None:
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.PROVIDER_NOT_CONFIGURED,
                "no current fixture provider is configured",
            )
        return self._provider

    @staticmethod
    def _require_supported(
        request: CurrentSeasonFixturesRequest,
        manifest: ProviderCapabilityManifest,
    ) -> None:
        if (
            manifest.source_id != request.scope.source_id
            or manifest.compatibility != request.compatibility
        ):
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.CAPABILITY_MANIFEST_INCOMPATIBLE,
                "provider capability metadata is incompatible with the request",
            )
        declaration = next(
            item
            for item in manifest.capabilities
            if item.capability is CurrentProviderCapability.FIXTURES
        )
        if declaration.availability is CapabilityAvailability.UNSUPPORTED:
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.CAPABILITY_UNSUPPORTED,
                "current fixture capability is unsupported",
            )
        if declaration.availability is CapabilityAvailability.TEMPORARILY_UNAVAILABLE:
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.CAPABILITY_TEMPORARILY_UNAVAILABLE,
                "current fixture capability is temporarily unavailable",
                retry_after_seconds=declaration.retry_after_seconds,
            )

    @staticmethod
    def _validate_response(
        request: CurrentSeasonFixturesRequest,
        response: CurrentSeasonFixturesResponse,
        entry: ProviderCacheEntry,
    ) -> None:
        expected_identity = provider_request_identity(request)
        capture = response.capture
        if (
            response.scope != request.scope
            or capture.request_identity != expected_identity
            or capture.request_identity != entry.request_identity
            or capture.response != entry.response
            or capture.retrieved_at != entry.fetched_at
            or capture.compatibility != request.compatibility
            or capture.compatibility.format_id != entry.compatibility_format_id
            or capture.page.request_cursor != request.page.cursor
        ):
            raise LiveFixtureReadError(
                LiveFixtureReadErrorCode.RESPONSE_INCOMPATIBLE,
                "fixture response provenance does not match its request",
            )

    @staticmethod
    def _extend_unique(
        target: list[CanonicalCurrentFixture],
        fixtures: Sequence[CanonicalCurrentFixture],
        *,
        provider_ids: set[str],
        canonical_ids: set[UUID],
    ) -> None:
        for item in fixtures:
            provider_id = item.observation.provider_fixture_id.external_id
            fixture_id = item.fixture.id
            if provider_id in provider_ids or fixture_id in canonical_ids:
                raise LiveFixtureReadError(
                    LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE,
                    "provider fixture pages contain duplicate identities",
                )
            provider_ids.add(provider_id)
            canonical_ids.add(fixture_id)
            target.append(item)

    @staticmethod
    def _provenance(
        entry: ProviderCacheEntry,
        source: LiveFixturePageSource,
    ) -> LiveFixturePageProvenance:
        return LiveFixturePageProvenance(
            source=source,
            cache_key_sha256=entry.cache_key_sha256,
            request_identity_sha256=entry.request_identity.sha256,
            response_sha256=entry.response.sha256,
            retrieved_at=entry.fetched_at,
            expires_at=entry.expires_at,
            compatibility_format_id=entry.compatibility_format_id,
        )
