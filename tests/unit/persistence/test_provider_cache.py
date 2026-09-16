"""Provider-cache write-plan and exact-byte reconstruction tests."""

from dataclasses import replace
from datetime import timedelta

import pytest

from pl_platform.ingestion.current import CurrentProviderCapability
from pl_platform.persistence.provider_cache import (
    ProviderCacheEntry,
    ProviderCacheLookup,
    ProviderCacheLookupStatus,
    provider_cache_write_plan,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    CanonicalizationProfile,
    PersistenceTable,
)
from tests.unit.ingestion.current_helpers import NOW, SOURCE, capture_for


def test_cache_plan_preserves_exact_objects_metadata_and_content_identity() -> None:
    capture = capture_for(CurrentProviderCapability.FIXTURES, 0)
    plan = provider_cache_write_plan(
        capture,
        expires_at=NOW + timedelta(minutes=5),
    )

    assert plan.kind is AggregateKind.PROVIDER_CACHE
    assert plan.identity == plan.rows[0].values[0].value
    assert plan.objects[0].payload == capture.request_identity.payload
    assert plan.objects[0].canonicalization_profile is (
        CanonicalizationProfile.IDENTITY_JSON
    )
    assert plan.objects[1].payload == capture.response.body
    assert plan.objects[1].canonicalization_profile is CanonicalizationProfile.OPAQUE
    assert plan.rows[0].table is PersistenceTable.PROVIDER_RESPONSE
    values = {item.name: item.value for item in plan.rows[0].values}
    assert values["capability"] == "fixtures"
    assert values["request_identity_sha256"] == capture.request_identity.sha256
    assert values["response_sha256"] == capture.response.sha256


def test_cache_plan_requires_strictly_later_utc_expiry() -> None:
    capture = capture_for(CurrentProviderCapability.TEAMS, 0)
    with pytest.raises(ValueError, match="follow retrieval"):
        provider_cache_write_plan(capture, expires_at=NOW)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        provider_cache_write_plan(
            capture,
            expires_at=(NOW + timedelta(minutes=1)).replace(tzinfo=None),
        )


def test_cache_entry_revalidates_identity_and_freshness() -> None:
    capture = capture_for(CurrentProviderCapability.FIXTURES, 0)
    plan = provider_cache_write_plan(
        capture,
        expires_at=NOW + timedelta(minutes=5),
    )
    entry = ProviderCacheEntry(
        cache_key_sha256=plan.identity,
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        request_identity=capture.request_identity,
        response=capture.response,
        fetched_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        compatibility_format_id=capture.compatibility.format_id,
    )

    assert entry.is_fresh_at(NOW)
    assert not entry.is_fresh_at(NOW + timedelta(minutes=5))
    with pytest.raises(ValueError, match="cache key"):
        ProviderCacheEntry(
            cache_key_sha256="0" * 64,
            source_id=SOURCE,
            capability=CurrentProviderCapability.FIXTURES,
            request_identity=capture.request_identity,
            response=capture.response,
            fetched_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            compatibility_format_id=capture.compatibility.format_id,
        )
    with pytest.raises(ValueError, match="compatibility"):
        replace(entry, compatibility_format_id="incompatible-format")

    rebuilt = ProviderCacheEntry.from_capture(
        capture,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert rebuilt == entry


def test_cache_lookup_state_requires_entry_except_for_miss() -> None:
    capture = capture_for(CurrentProviderCapability.FIXTURES, 0)
    entry = ProviderCacheEntry.from_capture(
        capture,
        expires_at=NOW + timedelta(minutes=5),
    )

    assert ProviderCacheLookup(ProviderCacheLookupStatus.FRESH, entry).entry is entry
    assert ProviderCacheLookup(ProviderCacheLookupStatus.MISS, None).entry is None
    with pytest.raises(ValueError, match="must agree"):
        ProviderCacheLookup(ProviderCacheLookupStatus.STALE, None)
