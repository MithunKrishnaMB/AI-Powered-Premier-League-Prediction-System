"""Cache-aware provider-neutral live fixture read tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from pl_platform.domain.current import (
    CurrentSeasonFixture,
    CurrentSeasonTeam,
    ProviderFixtureIdentifier,
    ProviderKickoff,
    ProviderTeamIdentifier,
)
from pl_platform.domain.fixtures import FixtureStatus, KickoffPrecision
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.ingestion.current import (
    CAPABILITY_ORDER,
    CAPABILITY_REQUIREMENTS,
    CapabilityAvailability,
    CapabilityDeclaration,
    CurrentProviderCapability,
    CurrentSeasonFixturesRequest,
    CurrentSeasonFixturesResponse,
    ExactProviderResponse,
    PageMetadata,
    ProviderCapabilityManifest,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    provider_request_identity,
)
from pl_platform.ingestion.current_transform import (
    CurrentTeamResolution,
    ResolvedCurrentSeasonTeam,
)
from pl_platform.ingestion.live_fixtures import (
    CacheAwareLiveFixtureReader,
    LiveFixturePageSource,
    LiveFixtureReadError,
    LiveFixtureReadErrorCode,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheCompatibilityError,
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
)
from tests.unit.ingestion.current_helpers import (
    NOW,
    SOURCE,
    compatibility,
    registry_and_season,
    scope,
)

LOOKUP_AT = NOW + timedelta(minutes=1)


def test_import_does_not_create_database_or_provider_dependencies() -> None:
    script = """
import pl_platform.persistence.database as database

def fail(*args, **kwargs):
    raise AssertionError("live fixture import performed runtime work")

database.create_database_engine = fail
import pl_platform.ingestion.live_fixtures
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def _fixture(external_id: str, home: int = 0, away: int = 1) -> CurrentSeasonFixture:
    return CurrentSeasonFixture(
        provider_fixture_id=ProviderFixtureIdentifier(
            source_id=SOURCE,
            external_id=external_id,
        ),
        home_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=f"provider-{home:02d}",
        ),
        away_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=f"provider-{away:02d}",
        ),
        kickoff=ProviderKickoff(
            kickoff_at=datetime(2026, 9, 20 + home, 14, tzinfo=UTC),
            precision=KickoffPrecision.EXACT,
            source_timezone="Europe/London",
            source_local_date=datetime(2026, 9, 20 + home).date(),
        ),
        status=FixtureStatus.SCHEDULED,
        matchweek=5,
        provider_updated_at=NOW,
    )


def _capture(
    request: CurrentSeasonFixturesRequest,
    items: tuple[CurrentSeasonFixture, ...],
    *,
    retrieved_at: datetime = NOW,
    next_cursor: str | None = None,
    body: bytes | None = None,
) -> ProviderResponseCapture:
    exact_body = body or (
        f'{{"cursor":{request.page.cursor!r},"count":{len(items)}}}\n'.encode()
    )
    return ProviderResponseCapture(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity=provider_request_identity(request),
        retrieved_at=retrieved_at,
        compatibility=request.compatibility,
        page=PageMetadata(
            request_cursor=request.page.cursor,
            returned_count=len(items),
            has_more=next_cursor is not None,
            next_cursor=next_cursor,
        ),
        quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
        response=ExactProviderResponse(
            body=exact_body,
            sha256=hashlib.sha256(exact_body).hexdigest(),
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        ),
    )


def _response(
    request: CurrentSeasonFixturesRequest,
    items: tuple[CurrentSeasonFixture, ...],
    *,
    retrieved_at: datetime = NOW,
    next_cursor: str | None = None,
) -> CurrentSeasonFixturesResponse:
    return CurrentSeasonFixturesResponse(
        scope=request.scope,
        items=items,
        capture=_capture(
            request,
            items,
            retrieved_at=retrieved_at,
            next_cursor=next_cursor,
        ),
    )


def _manifest(
    availability: CapabilityAvailability = CapabilityAvailability.SUPPORTED,
) -> ProviderCapabilityManifest:
    declarations: list[CapabilityDeclaration] = []
    for capability in CAPABILITY_ORDER:
        fixture_capability = capability is CurrentProviderCapability.FIXTURES
        selected = (
            availability if fixture_capability else CapabilityAvailability.UNSUPPORTED
        )
        declarations.append(
            CapabilityDeclaration(
                capability=capability,
                availability=selected,
                requirement=CAPABILITY_REQUIREMENTS[capability],
                supports_pagination=fixture_capability
                and selected is not CapabilityAvailability.UNSUPPORTED,
                maximum_page_size=(
                    100
                    if fixture_capability
                    and selected is not CapabilityAvailability.UNSUPPORTED
                    else None
                ),
                reason=None
                if selected is CapabilityAvailability.SUPPORTED
                else "absent",
                retry_after_seconds=(
                    30
                    if selected is CapabilityAvailability.TEMPORARILY_UNAVAILABLE
                    else None
                ),
            )
        )
    return ProviderCapabilityManifest(
        source_id=SOURCE,
        observed_at=NOW,
        compatibility=compatibility(),
        capabilities=tuple(declarations),
    )


def _resolution() -> tuple[CurrentTeamResolution, PremierLeagueSeason]:
    registry, season = registry_and_season()
    resolved = []
    for ordinal in range(2):
        provider_id = ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=f"provider-{ordinal:02d}",
        )
        resolved.append(
            ResolvedCurrentSeasonTeam(
                observation=CurrentSeasonTeam(
                    provider_team_id=provider_id,
                    provider_name=f"Provider Team {ordinal:02d}",
                ),
                canonical_team=registry.resolve_provider_team(
                    SOURCE,
                    provider_id.external_id,
                    f"Provider Team {ordinal:02d}",
                ),
                capture=_capture(
                    CurrentSeasonFixturesRequest(
                        scope=scope(), compatibility=compatibility()
                    ),
                    (),
                ),
            )
        )
    return (
        CurrentTeamResolution(
            source_id=SOURCE,
            competition_id=scope().competition_id,
            season_id=scope().season_id,
            teams=tuple(resolved),
        ),
        season,
    )


@dataclass
class FakeCache:
    lookups: dict[str, ProviderCacheLookup] = field(default_factory=dict)
    error: Exception | None = None
    stores: list[tuple[ProviderResponseCapture, datetime]] = field(default_factory=list)

    def lookup_latest(
        self,
        *,
        source_id: str,
        capability: CurrentProviderCapability,
        request_identity_sha256: str,
        at: datetime,
    ) -> ProviderCacheLookup:
        assert source_id == SOURCE
        assert capability is CurrentProviderCapability.FIXTURES
        assert at == LOOKUP_AT
        if self.error is not None:
            raise self.error
        return self.lookups.get(
            request_identity_sha256,
            ProviderCacheLookup(ProviderCacheLookupStatus.MISS, None),
        )

    def store(
        self,
        capture: ProviderResponseCapture,
        *,
        expires_at: datetime,
    ) -> object:
        self.stores.append((capture, expires_at))
        return object()


@dataclass
class FakeDecoder:
    items_by_cursor: dict[str | None, tuple[CurrentSeasonFixture, ...]]
    next_by_cursor: dict[str | None, str | None] = field(default_factory=dict)
    fail: bool = False
    retrieved_delta: timedelta = timedelta(0)

    def decode_current_season_fixtures(
        self,
        *,
        request: CurrentSeasonFixturesRequest,
        entry: ProviderCacheEntry,
    ) -> CurrentSeasonFixturesResponse:
        if self.fail:
            raise ValueError("decoder rejected bytes")
        items = self.items_by_cursor[request.page.cursor]
        capture = ProviderResponseCapture(
            source_id=entry.source_id,
            capability=entry.capability,
            request_identity=entry.request_identity,
            retrieved_at=entry.fetched_at + self.retrieved_delta,
            compatibility=request.compatibility,
            page=PageMetadata(
                request_cursor=request.page.cursor,
                returned_count=len(items),
                has_more=self.next_by_cursor.get(request.page.cursor) is not None,
                next_cursor=self.next_by_cursor.get(request.page.cursor),
            ),
            quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
            response=entry.response,
        )
        return CurrentSeasonFixturesResponse(
            scope=request.scope,
            items=items,
            capture=capture,
        )


@dataclass
class FakeProvider:
    manifest: ProviderCapabilityManifest
    items_by_cursor: dict[str | None, tuple[CurrentSeasonFixture, ...]]
    next_by_cursor: dict[str | None, str | None] = field(default_factory=dict)
    calls: list[str | None] = field(default_factory=list)

    def describe_capabilities(self) -> ProviderCapabilityManifest:
        return self.manifest

    def get_current_season_fixtures(
        self,
        request: CurrentSeasonFixturesRequest,
    ) -> CurrentSeasonFixturesResponse:
        cursor = request.page.cursor
        self.calls.append(cursor)
        return _response(
            request,
            self.items_by_cursor[cursor],
            retrieved_at=LOOKUP_AT,
            next_cursor=self.next_by_cursor.get(cursor),
        )


def _request() -> CurrentSeasonFixturesRequest:
    return CurrentSeasonFixturesRequest(scope=scope(), compatibility=compatibility())


def _entry(
    request: CurrentSeasonFixturesRequest,
    items: tuple[CurrentSeasonFixture, ...],
    *,
    expires_at: datetime,
) -> ProviderCacheEntry:
    return ProviderCacheEntry.from_capture(
        _capture(request, items),
        expires_at=expires_at,
    )


def test_fresh_cache_hit_reuses_exact_bytes_without_provider() -> None:
    request = _request()
    items = (_fixture("fixture-1"),)
    entry = _entry(request, items, expires_at=LOOKUP_AT + timedelta(minutes=4))
    cache = FakeCache(
        lookups={
            provider_request_identity(request).sha256: ProviderCacheLookup(
                ProviderCacheLookupStatus.FRESH,
                entry,
            )
        }
    )
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=cache,
        decoder=FakeDecoder({None: items}),
        provider=None,
        cache_ttl=timedelta(minutes=5),
    )

    result = reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert len(result.fixtures) == 1
    assert result.pages[0].source is LiveFixturePageSource.FRESH_CACHE
    assert result.pages[0].response_sha256 == entry.response.sha256
    assert not cache.stores


@pytest.mark.parametrize(
    ("status", "expected_source"),
    (
        (
            ProviderCacheLookupStatus.STALE,
            LiveFixturePageSource.STALE_CACHE_REFRESHED,
        ),
        (
            ProviderCacheLookupStatus.MISS,
            LiveFixturePageSource.CACHE_MISS_REFRESHED,
        ),
    ),
)
def test_stale_and_missing_entries_refresh_and_store_exact_capture(
    status: ProviderCacheLookupStatus,
    expected_source: LiveFixturePageSource,
) -> None:
    request = _request()
    items = (_fixture("fixture-1"),)
    stale = _entry(request, items, expires_at=LOOKUP_AT)
    cache = FakeCache(
        lookups={
            provider_request_identity(request).sha256: ProviderCacheLookup(
                status,
                None if status is ProviderCacheLookupStatus.MISS else stale,
            )
        }
    )
    provider = FakeProvider(_manifest(), {None: items})
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=cache,
        decoder=FakeDecoder({None: items}),
        provider=provider,
        cache_ttl=timedelta(minutes=5),
    )

    result = reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert provider.calls == [None]
    assert result.pages[0].source is expected_source
    assert cache.stores[0][0].response.body == result.fixtures[0].capture.response.body
    assert cache.stores[0][1] == LOOKUP_AT + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("availability", "code"),
    (
        (
            CapabilityAvailability.UNSUPPORTED,
            LiveFixtureReadErrorCode.CAPABILITY_UNSUPPORTED,
        ),
        (
            CapabilityAvailability.TEMPORARILY_UNAVAILABLE,
            LiveFixtureReadErrorCode.CAPABILITY_TEMPORARILY_UNAVAILABLE,
        ),
    ),
)
def test_refresh_requires_an_available_fixture_capability(
    availability: CapabilityAvailability,
    code: LiveFixtureReadErrorCode,
) -> None:
    request = _request()
    provider = FakeProvider(_manifest(availability), {None: (_fixture("fixture-1"),)})
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=provider,
        cache_ttl=timedelta(minutes=5),
    )

    with pytest.raises(LiveFixtureReadError) as captured:
        reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert captured.value.code is code
    assert provider.calls == []
    if availability is CapabilityAvailability.TEMPORARILY_UNAVAILABLE:
        assert captured.value.retry_after_seconds == 30


def test_cache_miss_without_provider_and_incompatible_cache_fail_closed() -> None:
    request = _request()
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=None,
        cache_ttl=timedelta(minutes=5),
    )
    with pytest.raises(LiveFixtureReadError) as missing:
        reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)
    assert missing.value.code is LiveFixtureReadErrorCode.PROVIDER_NOT_CONFIGURED

    incompatible = CacheAwareLiveFixtureReader(
        cache=FakeCache(error=ProviderCacheCompatibilityError("incompatible")),
        decoder=FakeDecoder({}),
        provider=FakeProvider(_manifest(), {}),
        cache_ttl=timedelta(minutes=5),
    )
    with pytest.raises(LiveFixtureReadError) as corrupted:
        incompatible.read(request, resolution=resolution, season=season, at=LOOKUP_AT)
    assert corrupted.value.code is LiveFixtureReadErrorCode.CACHE_INCOMPATIBLE


def test_paginated_refresh_is_complete_ordered_and_duplicate_safe() -> None:
    request = _request()
    first = (_fixture("fixture-1", 1, 0),)
    second = (_fixture("fixture-2", 0, 1),)
    provider = FakeProvider(
        _manifest(),
        {None: first, "next": second},
        {None: "next"},
    )
    cache = FakeCache()
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=cache,
        decoder=FakeDecoder({}),
        provider=provider,
        cache_ttl=timedelta(minutes=5),
    )

    result = reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert provider.calls == [None, "next"]
    assert len(result.fixtures) == len(result.pages) == 2
    assert [
        item.observation.provider_fixture_id.external_id for item in result.fixtures
    ] == [
        "fixture-2",
        "fixture-1",
    ]

    duplicate_provider = FakeProvider(
        _manifest(),
        {None: second, "next": (_fixture("fixture-3", 0, 1),)},
        {None: "next"},
    )
    duplicate_reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=duplicate_provider,
        cache_ttl=timedelta(minutes=5),
    )
    with pytest.raises(LiveFixtureReadError) as duplicate:
        duplicate_reader.read(
            request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert duplicate.value.code is LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE


def test_invalid_lookup_time_ttl_and_cached_decoder_fail_deterministically() -> None:
    request = _request()
    items = (_fixture("fixture-1"),)
    entry = _entry(request, items, expires_at=LOOKUP_AT + timedelta(minutes=1))
    cache = FakeCache(
        lookups={
            provider_request_identity(request).sha256: ProviderCacheLookup(
                ProviderCacheLookupStatus.FRESH,
                entry,
            )
        }
    )
    with pytest.raises(ValueError, match="TTL"):
        CacheAwareLiveFixtureReader(
            cache=cache,
            decoder=FakeDecoder({}),
            provider=None,
            cache_ttl=timedelta(0),
        )

    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=cache,
        decoder=FakeDecoder({None: items}, fail=True),
        provider=None,
        cache_ttl=timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        reader.read(
            request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT.replace(tzinfo=None),
        )
    with pytest.raises(LiveFixtureReadError) as decoded:
        reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)
    assert decoded.value.code is LiveFixtureReadErrorCode.CACHE_INCOMPATIBLE


def test_read_requires_first_page_and_matching_capability_manifest() -> None:
    request = _request()
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=FakeProvider(_manifest(), {}),
        cache_ttl=timedelta(minutes=1),
    )
    later_request = request.model_copy(
        update={"page": request.page.model_copy(update={"cursor": "later"})}
    )
    with pytest.raises(LiveFixtureReadError) as later:
        reader.read(
            later_request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert later.value.code is LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE

    mismatch = FakeProvider(
        _manifest().model_copy(update={"source_id": "another-provider"}),
        {},
    )
    mismatched_reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=mismatch,
        cache_ttl=timedelta(minutes=1),
    )
    with pytest.raises(LiveFixtureReadError) as incompatible:
        mismatched_reader.read(
            request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert (
        incompatible.value.code
        is LiveFixtureReadErrorCode.CAPABILITY_MANIFEST_INCOMPATIBLE
    )


def test_cached_provenance_and_canonical_resolution_fail_closed() -> None:
    request = _request()
    items = (_fixture("fixture-1"),)
    entry = _entry(request, items, expires_at=LOOKUP_AT + timedelta(minutes=1))
    lookup = ProviderCacheLookup(ProviderCacheLookupStatus.FRESH, entry)
    resolution, season = _resolution()
    provenance_reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(lookups={provider_request_identity(request).sha256: lookup}),
        decoder=FakeDecoder({None: items}, retrieved_delta=timedelta(seconds=1)),
        provider=None,
        cache_ttl=timedelta(minutes=1),
    )
    with pytest.raises(LiveFixtureReadError) as provenance:
        provenance_reader.read(
            request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert provenance.value.code is LiveFixtureReadErrorCode.RESPONSE_INCOMPATIBLE

    unresolved = (_fixture("fixture-2", 2, 1),)
    canonical_reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=FakeProvider(_manifest(), {None: unresolved}),
        cache_ttl=timedelta(minutes=1),
    )
    with pytest.raises(LiveFixtureReadError) as canonical:
        canonical_reader.read(
            request,
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert canonical.value.code is LiveFixtureReadErrorCode.CANONICALIZATION_FAILED


def test_provider_pagination_cycle_fails_before_repeating_a_request() -> None:
    request = _request()
    provider = FakeProvider(
        _manifest(),
        {None: (), "a": (), "b": ()},
        {None: "a", "a": "b", "b": "a"},
    )
    resolution, season = _resolution()
    reader = CacheAwareLiveFixtureReader(
        cache=FakeCache(),
        decoder=FakeDecoder({}),
        provider=provider,
        cache_ttl=timedelta(minutes=1),
    )

    with pytest.raises(LiveFixtureReadError) as cycle:
        reader.read(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert cycle.value.code is LiveFixtureReadErrorCode.PAGINATION_INCOMPATIBLE
    assert provider.calls == [None, "a", "b"]
