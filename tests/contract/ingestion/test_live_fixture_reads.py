"""Offline exact-byte contract for cache-aware live fixture reads."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentSeasonFixturesRequest,
    CurrentSeasonFixturesResponse,
    PageMetadata,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
)
from pl_platform.ingestion.current_transform import CurrentTeamResolution
from pl_platform.ingestion.live_fixtures import (
    CacheAwareLiveFixtureReader,
    LiveFixturePageSource,
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
from tests.unit.ingestion.current_helpers import registry_and_season, request_for

FIXTURE_ROOT = Path("tests/fixtures/current_provider")


@dataclass(frozen=True)
class ExactCache:
    entry: ProviderCacheEntry

    def lookup_latest(self, **_: object) -> ProviderCacheLookup:
        return ProviderCacheLookup(ProviderCacheLookupStatus.FRESH, self.entry)

    def store(self, *_: object, **__: object) -> object:
        raise AssertionError("fresh recorded bytes must not be stored again")


class RecordedFixtureDecoder:
    def decode_current_season_fixtures(
        self,
        *,
        request: CurrentSeasonFixturesRequest,
        entry: ProviderCacheEntry,
    ) -> CurrentSeasonFixturesResponse:
        payload = json.loads(entry.response.body.decode(entry.response.encoding))
        assert payload == {
            "operation": CurrentProviderCapability.FIXTURES.value,
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
        return CurrentSeasonFixturesResponse(
            scope=request.scope,
            items=(),
            capture=capture,
        )


def test_recorded_fixture_bytes_are_reused_without_provider_contact() -> None:
    manifest = load_recorded_manifest(FIXTURE_ROOT / "manifest.json")
    spec = next(
        item
        for item in manifest.recordings
        if item.capability is CurrentProviderCapability.FIXTURES
    )
    request = request_for(CurrentProviderCapability.FIXTURES)
    assert isinstance(request, CurrentSeasonFixturesRequest)
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
    reader = CacheAwareLiveFixtureReader(
        cache=ExactCache(entry),
        decoder=RecordedFixtureDecoder(),
        provider=None,
        cache_ttl=timedelta(minutes=5),
    )

    result = reader.read(
        request,
        resolution=resolution,
        season=season,
        at=capture.retrieved_at + timedelta(minutes=1),
    )

    assert result.fixtures == ()
    assert result.pages[0].source is LiveFixturePageSource.FRESH_CACHE
    assert result.pages[0].response_sha256 == spec.response_sha256
