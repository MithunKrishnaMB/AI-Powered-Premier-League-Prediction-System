"""Exact-cache-aware final-match reconciliation tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from pl_platform.domain.current import (
    CompletedFixtureResult,
    ProviderFixtureIdentifier,
    ProviderTeamIdentifier,
)
from pl_platform.domain.fixtures import FixtureScore, MatchOutcome
from pl_platform.ingestion.current import (
    CAPABILITY_ORDER,
    CAPABILITY_REQUIREMENTS,
    CapabilityAvailability,
    CapabilityDeclaration,
    CompletedResultsRequest,
    CompletedResultsResponse,
    CurrentProviderCapability,
    ExactProviderResponse,
    PageMetadata,
    ProviderCapabilityManifest,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    provider_request_identity,
)
from pl_platform.ingestion.final_results import (
    CacheAwareFinalResultReconciler,
    FinalResultErrorCode,
    FinalResultPageSource,
    FinalResultReconciliationError,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheCompatibilityError,
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
)
from pl_platform.persistence.repositories import AggregateKind, PersistenceResult
from tests.unit.ingestion.current_helpers import (
    NOW,
    SOURCE,
    compatibility,
    scope,
)
from tests.unit.ingestion.test_current_reconciliation import _resolution

LOOKUP_AT = NOW + timedelta(minutes=1)


def _request(cursor: str | None = None) -> CompletedResultsRequest:
    request = CompletedResultsRequest(scope=scope(), compatibility=compatibility())
    return request.model_copy(
        update={"page": request.page.model_copy(update={"cursor": cursor})}
    )


def _result(
    external_id: str,
    *,
    home: int = 0,
    away: int = 1,
) -> CompletedFixtureResult:
    return CompletedFixtureResult(
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
        full_time_score=FixtureScore(home=2, away=1),
        outcome=MatchOutcome.HOME_WIN,
        completed_at=NOW - timedelta(minutes=1),
    )


def _response(
    request: CompletedResultsRequest,
    items: tuple[CompletedFixtureResult, ...],
    *,
    next_cursor: str | None = None,
    retrieved_at: datetime = NOW,
) -> CompletedResultsResponse:
    body = f'{{"cursor":{request.page.cursor!r},"count":{len(items)}}}\n'.encode()
    capture = ProviderResponseCapture(
        source_id=SOURCE,
        capability=CurrentProviderCapability.COMPLETED_RESULTS,
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
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        ),
    )
    return CompletedResultsResponse(scope=request.scope, items=items, capture=capture)


def _manifest(
    availability: CapabilityAvailability = CapabilityAvailability.SUPPORTED,
    *,
    source_id: str = SOURCE,
) -> ProviderCapabilityManifest:
    declarations = []
    for capability in CAPABILITY_ORDER:
        selected = (
            availability
            if capability is CurrentProviderCapability.COMPLETED_RESULTS
            else CapabilityAvailability.UNSUPPORTED
        )
        declarations.append(
            CapabilityDeclaration(
                capability=capability,
                availability=selected,
                requirement=CAPABILITY_REQUIREMENTS[capability],
                supports_pagination=(
                    capability is CurrentProviderCapability.COMPLETED_RESULTS
                    and selected is not CapabilityAvailability.UNSUPPORTED
                ),
                maximum_page_size=(
                    100
                    if capability is CurrentProviderCapability.COMPLETED_RESULTS
                    and selected is not CapabilityAvailability.UNSUPPORTED
                    else None
                ),
                reason=(
                    None
                    if selected is CapabilityAvailability.SUPPORTED
                    else "unavailable"
                ),
                retry_after_seconds=(
                    30
                    if selected is CapabilityAvailability.TEMPORARILY_UNAVAILABLE
                    else None
                ),
            )
        )
    return ProviderCapabilityManifest(
        source_id=source_id,
        observed_at=NOW,
        compatibility=compatibility(),
        capabilities=tuple(declarations),
    )


@dataclass
class _Cache:
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
        assert capability is CurrentProviderCapability.COMPLETED_RESULTS
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
class _Decoder:
    items: tuple[CompletedFixtureResult, ...]
    fail: bool = False
    retrieved_delta: timedelta = timedelta(0)

    def decode_completed_results(
        self,
        *,
        request: CompletedResultsRequest,
        entry: ProviderCacheEntry,
    ) -> CompletedResultsResponse:
        if self.fail:
            raise ValueError("bad bytes")
        response = _response(
            request,
            self.items,
            retrieved_at=entry.fetched_at + self.retrieved_delta,
        )
        return response.model_copy(
            update={
                "capture": response.capture.model_copy(
                    update={"response": entry.response}
                )
            }
        )


@dataclass
class _Provider:
    manifest: ProviderCapabilityManifest
    items_by_cursor: dict[str | None, tuple[CompletedFixtureResult, ...]]
    next_by_cursor: dict[str | None, str | None] = field(default_factory=dict)
    calls: list[str | None] = field(default_factory=list)

    def describe_capabilities(self) -> ProviderCapabilityManifest:
        return self.manifest

    def get_completed_results(
        self,
        request: CompletedResultsRequest,
    ) -> CompletedResultsResponse:
        self.calls.append(request.page.cursor)
        return _response(
            request,
            self.items_by_cursor[request.page.cursor],
            next_cursor=self.next_by_cursor.get(request.page.cursor),
            retrieved_at=LOOKUP_AT,
        )


@dataclass
class _Repository:
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def reconcile_results(self, results: tuple[object, ...]) -> PersistenceResult:
        self.calls.append(results)
        return PersistenceResult(
            AggregateKind.CURRENT_RESULTS,
            "result-sync",
            "0" * 64,
            0,
            0,
            len(results),
            0,
        )


def _entry(
    response: CompletedResultsResponse,
    *,
    expires_at: datetime = LOOKUP_AT + timedelta(minutes=5),
) -> ProviderCacheEntry:
    return ProviderCacheEntry.from_capture(response.capture, expires_at=expires_at)


def _reconciler(
    *,
    cache: _Cache,
    decoder: _Decoder,
    repository: _Repository,
    provider: _Provider | None = None,
) -> CacheAwareFinalResultReconciler:
    return CacheAwareFinalResultReconciler(
        cache=cache,
        decoder=decoder,
        repository=repository,
        provider=provider,
        cache_ttl=timedelta(minutes=10),
    )


def test_fresh_exact_cache_reconciles_once_without_provider() -> None:
    request = _request()
    response = _response(request, (_result("fixture-1"),))
    entry = _entry(response)
    cache = _Cache(
        {
            provider_request_identity(request).sha256: ProviderCacheLookup(
                ProviderCacheLookupStatus.FRESH, entry
            )
        }
    )
    repository = _Repository()
    resolution, season = _resolution()

    reconciled = _reconciler(
        cache=cache,
        decoder=_Decoder(response.items),
        repository=repository,
    ).reconcile(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert len(reconciled.results) == 1
    assert len(repository.calls) == 1
    assert reconciled.pages[0].source is FinalResultPageSource.FRESH_CACHE
    assert reconciled.pages[0].response_sha256 == response.capture.response.sha256
    assert cache.stores == []


@pytest.mark.parametrize(
    ("status", "source"),
    (
        (ProviderCacheLookupStatus.MISS, FinalResultPageSource.CACHE_MISS_REFRESHED),
        (ProviderCacheLookupStatus.STALE, FinalResultPageSource.STALE_CACHE_REFRESHED),
    ),
)
def test_miss_and_stale_refresh_through_provider(
    status: ProviderCacheLookupStatus,
    source: FinalResultPageSource,
) -> None:
    request = _request()
    lookup_entry = (
        _entry(
            _response(request, (_result("old"),)),
            expires_at=NOW + timedelta(seconds=30),
        )
        if status is ProviderCacheLookupStatus.STALE
        else None
    )
    cache = _Cache(
        {
            provider_request_identity(request).sha256: ProviderCacheLookup(
                status, lookup_entry
            )
        }
    )
    provider = _Provider(_manifest(), {None: (_result("fixture-1"),)})
    resolution, season = _resolution()

    reconciled = _reconciler(
        cache=cache,
        decoder=_Decoder(()),
        repository=_Repository(),
        provider=provider,
    ).reconcile(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert reconciled.pages[0].source is source
    assert provider.calls == [None]
    assert cache.stores[0][1] == LOOKUP_AT + timedelta(minutes=10)


def test_empty_fresh_result_does_not_open_reconciliation_write() -> None:
    request = _request()
    response = _response(request, ())
    cache = _Cache(
        {
            provider_request_identity(request).sha256: ProviderCacheLookup(
                ProviderCacheLookupStatus.FRESH, _entry(response)
            )
        }
    )
    repository = _Repository()
    resolution, season = _resolution()

    result = _reconciler(
        cache=cache,
        decoder=_Decoder(()),
        repository=repository,
    ).reconcile(request, resolution=resolution, season=season, at=LOOKUP_AT)

    assert result.persistence is None
    assert repository.calls == []


@pytest.mark.parametrize(
    ("provider", "code"),
    (
        (None, FinalResultErrorCode.PROVIDER_NOT_CONFIGURED),
        (
            _Provider(_manifest(CapabilityAvailability.UNSUPPORTED), {None: ()}),
            FinalResultErrorCode.CAPABILITY_UNSUPPORTED,
        ),
        (
            _Provider(
                _manifest(CapabilityAvailability.TEMPORARILY_UNAVAILABLE), {None: ()}
            ),
            FinalResultErrorCode.CAPABILITY_TEMPORARILY_UNAVAILABLE,
        ),
        (
            _Provider(_manifest(source_id="wrong-source"), {None: ()}),
            FinalResultErrorCode.CAPABILITY_MANIFEST_INCOMPATIBLE,
        ),
    ),
)
def test_unavailable_provider_capability_fails_closed(
    provider: _Provider | None,
    code: FinalResultErrorCode,
) -> None:
    resolution, season = _resolution()
    with pytest.raises(FinalResultReconciliationError) as captured:
        _reconciler(
            cache=_Cache(),
            decoder=_Decoder(()),
            repository=_Repository(),
            provider=provider,
        ).reconcile(_request(), resolution=resolution, season=season, at=LOOKUP_AT)

    assert captured.value.code is code
    if code is FinalResultErrorCode.CAPABILITY_TEMPORARILY_UNAVAILABLE:
        assert captured.value.retry_after_seconds == 30


def test_cache_metadata_or_bytes_incompatibility_fails_closed() -> None:
    request = _request()
    response = _response(request, ())
    entry = _entry(response)
    resolution, season = _resolution()
    for cache, decoder in (
        (_Cache(error=ProviderCacheCompatibilityError("bad")), _Decoder(())),
        (
            _Cache(
                {
                    provider_request_identity(request).sha256: ProviderCacheLookup(
                        ProviderCacheLookupStatus.FRESH, entry
                    )
                }
            ),
            _Decoder((), fail=True),
        ),
        (
            _Cache(
                {
                    provider_request_identity(request).sha256: ProviderCacheLookup(
                        ProviderCacheLookupStatus.FRESH, entry
                    )
                }
            ),
            _Decoder((), retrieved_delta=timedelta(seconds=1)),
        ),
    ):
        with pytest.raises(FinalResultReconciliationError) as captured:
            _reconciler(
                cache=cache,
                decoder=decoder,
                repository=_Repository(),
            ).reconcile(request, resolution=resolution, season=season, at=LOOKUP_AT)
        assert captured.value.code in {
            FinalResultErrorCode.CACHE_INCOMPATIBLE,
            FinalResultErrorCode.RESPONSE_INCOMPATIBLE,
        }


def test_pagination_completes_before_one_reconciliation() -> None:
    provider = _Provider(
        _manifest(),
        {
            None: (_result("fixture-1"),),
            "next": (_result("fixture-2", home=2, away=3),),
        },
        {None: "next"},
    )
    repository = _Repository()
    resolution, season = _resolution()

    result = _reconciler(
        cache=_Cache(),
        decoder=_Decoder(()),
        repository=repository,
        provider=provider,
    ).reconcile(_request(), resolution=resolution, season=season, at=LOOKUP_AT)

    assert provider.calls == [None, "next"]
    assert len(result.pages) == 2
    assert len(repository.calls) == 1
    assert len(repository.calls[0]) == 2


def test_duplicate_pages_and_repeated_cursor_fail_before_persistence() -> None:
    resolution, season = _resolution()
    providers = (
        _Provider(
            _manifest(),
            {None: (_result("fixture-1"),), "next": (_result("fixture-1"),)},
            {None: "next"},
        ),
        _Provider(
            _manifest(),
            {None: (), "next": (), "later": ()},
            {None: "next", "next": "later", "later": "next"},
        ),
    )
    for provider in providers:
        repository = _Repository()
        with pytest.raises(FinalResultReconciliationError) as captured:
            _reconciler(
                cache=_Cache(),
                decoder=_Decoder(()),
                repository=repository,
                provider=provider,
            ).reconcile(_request(), resolution=resolution, season=season, at=LOOKUP_AT)
        assert captured.value.code is FinalResultErrorCode.PAGINATION_INCOMPATIBLE
        assert repository.calls == []


def test_invalid_start_time_ttl_and_canonical_mapping_are_rejected() -> None:
    resolution, season = _resolution()
    with pytest.raises(ValueError, match="TTL"):
        CacheAwareFinalResultReconciler(
            cache=_Cache(),
            decoder=_Decoder(()),
            repository=_Repository(),
            provider=None,
            cache_ttl=timedelta(0),
        )
    reconciler = _reconciler(
        cache=_Cache(),
        decoder=_Decoder(()),
        repository=_Repository(),
    )
    with pytest.raises(ValueError, match="UTC"):
        reconciler.reconcile(
            _request(),
            resolution=resolution,
            season=season,
            at=LOOKUP_AT.replace(tzinfo=None),
        )
    with pytest.raises(FinalResultReconciliationError) as paged:
        reconciler.reconcile(
            _request("next"),
            resolution=resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert paged.value.code is FinalResultErrorCode.PAGINATION_INCOMPATIBLE

    provider = _Provider(_manifest(), {None: (_result("bad", home=0, away=19),)})
    bad_resolution = resolution.__class__(
        resolution.source_id,
        resolution.competition_id,
        resolution.season_id,
        resolution.teams[:2],
    )
    with pytest.raises(FinalResultReconciliationError) as canonical:
        _reconciler(
            cache=_Cache(),
            decoder=_Decoder(()),
            repository=_Repository(),
            provider=provider,
        ).reconcile(
            _request(),
            resolution=bad_resolution,
            season=season,
            at=LOOKUP_AT,
        )
    assert canonical.value.code is FinalResultErrorCode.CANONICALIZATION_FAILED


def test_import_is_lazy() -> None:
    script = """
import pl_platform.persistence.database as database
def fail(*args, **kwargs):
    raise AssertionError("result reconciliation import performed runtime work")
database.create_database_engine = fail
import pl_platform.ingestion.final_results
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
