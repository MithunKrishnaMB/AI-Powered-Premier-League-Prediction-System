"""Offline exact-byte contract for final-match reconciliation."""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pl_platform.ingestion.current import (
    CompletedResultsRequest,
    CompletedResultsResponse,
    CurrentProviderCapability,
    PageMetadata,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
)
from pl_platform.ingestion.current_transform import CurrentTeamResolution
from pl_platform.ingestion.final_results import (
    CacheAwareFinalResultReconciler,
    FinalResultPageSource,
)
from pl_platform.ingestion.recorded import (
    load_recorded_manifest,
    replay_recorded_response,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
)
from pl_platform.persistence.repositories import PersistenceResult
from tests.unit.ingestion.current_helpers import registry_and_season, request_for

FIXTURE_ROOT = Path("tests/fixtures/current_provider")


@dataclass(frozen=True)
class _ExactCache:
    entry: ProviderCacheEntry

    def lookup_latest(self, **_: object) -> ProviderCacheLookup:
        return ProviderCacheLookup(ProviderCacheLookupStatus.FRESH, self.entry)

    def store(self, *_: object, **__: object) -> object:
        raise AssertionError("fresh recorded bytes must not be stored again")


class _RecordedDecoder:
    def decode_completed_results(
        self,
        *,
        request: CompletedResultsRequest,
        entry: ProviderCacheEntry,
    ) -> CompletedResultsResponse:
        payload = json.loads(entry.response.body.decode(entry.response.encoding))
        assert payload == {
            "operation": CurrentProviderCapability.COMPLETED_RESULTS.value,
            "records": [],
        }
        capture = ProviderResponseCapture(
            source_id=entry.source_id,
            capability=entry.capability,
            request_identity=entry.request_identity,
            retrieved_at=entry.fetched_at,
            compatibility=request.compatibility,
            page=PageMetadata(returned_count=0, has_more=False),
            quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
            response=entry.response,
        )
        return CompletedResultsResponse(scope=request.scope, items=(), capture=capture)


@dataclass
class _Repository:
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def reconcile_results(self, results: tuple[object, ...]) -> PersistenceResult:
        self.calls.append(results)
        raise AssertionError("empty completed-result set must not be persisted")


def test_recorded_result_bytes_are_reused_before_reconciliation() -> None:
    manifest = load_recorded_manifest(FIXTURE_ROOT / "manifest.json")
    spec = next(
        item
        for item in manifest.recordings
        if item.capability is CurrentProviderCapability.COMPLETED_RESULTS
    )
    request = request_for(CurrentProviderCapability.COMPLETED_RESULTS)
    assert isinstance(request, CompletedResultsRequest)
    capture = replay_recorded_response(root=FIXTURE_ROOT, request=request, spec=spec)
    entry = ProviderCacheEntry.from_capture(
        capture,
        expires_at=capture.retrieved_at + timedelta(hours=1),
    )
    _, season = registry_and_season()
    resolution = CurrentTeamResolution(
        source_id=request.scope.source_id,
        competition_id=request.scope.competition_id,
        season_id=request.scope.season_id,
        teams=(),
    )
    repository = _Repository()

    result = CacheAwareFinalResultReconciler(
        cache=_ExactCache(entry),
        decoder=_RecordedDecoder(),
        repository=repository,
        provider=None,
        cache_ttl=timedelta(minutes=5),
    ).reconcile(
        request,
        resolution=resolution,
        season=season,
        at=capture.retrieved_at + timedelta(minutes=1),
    )

    assert result.results == ()
    assert result.persistence is None
    assert repository.calls == []
    assert result.pages[0].source is FinalResultPageSource.FRESH_CACHE
    assert result.pages[0].response_sha256 == spec.response_sha256
