"""Contract tests for provider-neutral current-season ingestion."""

import hashlib
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pl_platform.domain.current import (
    CompletedFixtureResult,
    CurrentSeasonFixture,
    CurrentSeasonScope,
    CurrentSeasonTeam,
    FixtureStatusObservation,
    ProviderCompetitionIdentifier,
    ProviderFixtureIdentifier,
    ProviderKickoff,
    ProviderSeasonIdentifier,
    ProviderTeamIdentifier,
    StandingRow,
)
from pl_platform.domain.fixtures import (
    FixtureScore,
    FixtureStatus,
    KickoffPrecision,
    MatchOutcome,
)
from pl_platform.ingestion.current import (
    CAPABILITY_ORDER,
    CAPABILITY_REQUIREMENTS,
    PROVIDER_CACHE_CAPABILITY_BY_OPERATION,
    CapabilityAvailability,
    CapabilityDeclaration,
    CapabilityRequirement,
    CompletedResultsRequest,
    CompletedResultsResponse,
    CurrentProviderCapability,
    CurrentProviderRequest,
    CurrentSeasonFixturesRequest,
    CurrentSeasonFixturesResponse,
    CurrentSeasonTeamsRequest,
    CurrentSeasonTeamsResponse,
    ExactProviderResponse,
    FixtureStatusRequest,
    FixtureStatusResponse,
    PageMetadata,
    PageRequest,
    ProviderCapabilityManifest,
    ProviderCompatibility,
    ProviderError,
    ProviderErrorCode,
    ProviderOperationError,
    ProviderRequestIdentity,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    RetryDisposition,
    StandingsRequest,
    StandingsResponse,
    deterministic_provider_cache_key,
    provider_request_identity,
)

SOURCE = "test-provider"
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def _provider_team(value: str, source: str = SOURCE) -> ProviderTeamIdentifier:
    return ProviderTeamIdentifier(source_id=source, external_id=value)


def _provider_fixture(value: str, source: str = SOURCE) -> ProviderFixtureIdentifier:
    return ProviderFixtureIdentifier(source_id=source, external_id=value)


def _scope(source: str = SOURCE) -> CurrentSeasonScope:
    return CurrentSeasonScope(
        competition_id="eng-premier-league",
        season_id="2026-2027",
        provider_competition_id=ProviderCompetitionIdentifier(
            source_id=source, external_id="PL"
        ),
        provider_season_id=ProviderSeasonIdentifier(
            source_id=source, external_id="2026"
        ),
    )


def _compatibility() -> ProviderCompatibility:
    return ProviderCompatibility(
        provider_api_version="api-v1",
        parser_schema_version="parser-v1",
    )


def _request(capability: CurrentProviderCapability) -> CurrentProviderRequest:
    if capability is CurrentProviderCapability.TEAMS:
        return CurrentSeasonTeamsRequest(scope=_scope(), compatibility=_compatibility())
    if capability is CurrentProviderCapability.FIXTURES:
        return CurrentSeasonFixturesRequest(
            scope=_scope(), compatibility=_compatibility()
        )
    if capability is CurrentProviderCapability.FIXTURE_STATUS:
        return FixtureStatusRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            fixture_ids=(_provider_fixture("fixture-1"),),
        )
    if capability is CurrentProviderCapability.COMPLETED_RESULTS:
        return CompletedResultsRequest(scope=_scope(), compatibility=_compatibility())
    return StandingsRequest(scope=_scope(), compatibility=_compatibility())


def _exact_response(body: bytes = b'{"provider":"exact"}\n') -> ExactProviderResponse:
    return ExactProviderResponse(
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        http_status=200,
        media_type="application/json",
        encoding="utf-8",
        etag='"test"',
    )


def _capture(
    capability: CurrentProviderCapability,
    *,
    item_count: int,
    retrieved_at: datetime = NOW,
) -> ProviderResponseCapture:
    request = _request(capability)
    return ProviderResponseCapture(
        source_id=SOURCE,
        capability=capability,
        request_identity=provider_request_identity(request),
        retrieved_at=retrieved_at,
        provider_generated_at=retrieved_at - timedelta(seconds=1),
        compatibility=_compatibility(),
        page=PageMetadata(returned_count=item_count, has_more=False),
        quota=QuotaMetadata(status=QuotaStatus.UNKNOWN),
        response=_exact_response(),
    )


def _declarations() -> tuple[CapabilityDeclaration, ...]:
    return tuple(
        CapabilityDeclaration(
            capability=capability,
            availability=(
                CapabilityAvailability.UNSUPPORTED
                if capability is CurrentProviderCapability.STANDINGS
                else CapabilityAvailability.SUPPORTED
            ),
            requirement=CAPABILITY_REQUIREMENTS[capability],
            supports_pagination=capability is not CurrentProviderCapability.STANDINGS,
            maximum_page_size=(
                None if capability is CurrentProviderCapability.STANDINGS else 100
            ),
            reason=(
                "provider has no standings endpoint"
                if capability is CurrentProviderCapability.STANDINGS
                else None
            ),
        )
        for capability in CAPABILITY_ORDER
    )


def test_capability_manifest_is_complete_ordered_and_separates_optional() -> None:
    manifest = ProviderCapabilityManifest(
        source_id=SOURCE,
        observed_at=NOW,
        compatibility=_compatibility(),
        capabilities=_declarations(),
    )

    assert tuple(item.capability for item in manifest.capabilities) == CAPABILITY_ORDER
    assert manifest.capabilities[-1].requirement is CapabilityRequirement.OPTIONAL
    with pytest.raises(ValidationError, match="complete and canonically ordered"):
        ProviderCapabilityManifest(
            source_id=SOURCE,
            observed_at=NOW,
            compatibility=_compatibility(),
            capabilities=tuple(reversed(_declarations())),
        )
    changed = list(_declarations())
    changed[0] = changed[0].model_copy(
        update={"requirement": CapabilityRequirement.OPTIONAL}
    )
    with pytest.raises(ValidationError, match="platform policy"):
        ProviderCapabilityManifest(
            source_id=SOURCE,
            observed_at=NOW,
            compatibility=_compatibility(),
            capabilities=tuple(changed),
        )


def test_capability_availability_metadata_fails_closed() -> None:
    temporary = CapabilityDeclaration(
        capability=CurrentProviderCapability.FIXTURES,
        availability=CapabilityAvailability.TEMPORARILY_UNAVAILABLE,
        requirement=CapabilityRequirement.REQUIRED,
        supports_pagination=True,
        maximum_page_size=100,
        reason="maintenance",
        retry_after_seconds=60,
    )
    assert temporary.retry_after_seconds == 60

    invalid_payloads = (
        {
            "availability": CapabilityAvailability.SUPPORTED,
            "reason": "not actually available",
        },
        {
            "availability": CapabilityAvailability.TEMPORARILY_UNAVAILABLE,
            "reason": None,
        },
        {
            "availability": CapabilityAvailability.UNSUPPORTED,
            "reason": "absent",
            "supports_pagination": True,
            "maximum_page_size": 100,
        },
        {
            "availability": CapabilityAvailability.UNSUPPORTED,
            "reason": "absent",
            "retry_after_seconds": 60,
        },
        {"supports_pagination": False, "maximum_page_size": 100},
    )
    baseline = {
        "capability": CurrentProviderCapability.FIXTURES,
        "availability": CapabilityAvailability.SUPPORTED,
        "requirement": CapabilityRequirement.REQUIRED,
        "supports_pagination": True,
        "maximum_page_size": 100,
    }
    for changes in invalid_payloads:
        with pytest.raises(ValidationError):
            CapabilityDeclaration.model_validate({**baseline, **changes})


def test_pagination_and_quota_state_vocabulary_is_strict() -> None:
    page = PageMetadata(
        request_cursor="one",
        returned_count=2,
        has_more=True,
        next_cursor="two",
    )
    quota = QuotaMetadata(
        status=QuotaStatus.AVAILABLE,
        bucket="daily",
        limit=100,
        remaining=99,
        resets_at=NOW + timedelta(days=1),
    )

    assert page.next_cursor == "two"
    assert quota.remaining == 99
    with pytest.raises(ValidationError, match="must agree"):
        PageMetadata(returned_count=0, has_more=True)
    with pytest.raises(ValidationError, match="did not advance"):
        PageMetadata(
            request_cursor="same",
            returned_count=0,
            has_more=True,
            next_cursor="same",
        )
    for payload in (
        {"status": QuotaStatus.UNKNOWN, "limit": 1},
        {"status": QuotaStatus.AVAILABLE, "limit": 1},
        {"status": QuotaStatus.AVAILABLE, "limit": 1, "remaining": 2},
        {"status": QuotaStatus.AVAILABLE, "limit": 1, "remaining": 0},
        {"status": QuotaStatus.EXHAUSTED, "limit": 1, "remaining": 1},
        {"status": QuotaStatus.EXHAUSTED, "limit": 1, "remaining": 0},
    ):
        with pytest.raises(ValidationError):
            QuotaMetadata.model_validate(payload)

    exhausted = QuotaMetadata(
        status=QuotaStatus.EXHAUSTED,
        limit=10,
        remaining=0,
        retry_after_seconds=30,
    )
    assert exhausted.status is QuotaStatus.EXHAUSTED
    assert QuotaMetadata(status=QuotaStatus.UNLIMITED).limit is None


def test_request_identity_and_cache_key_are_exact_deterministic_and_secret_free() -> (
    None
):
    request = CurrentSeasonFixturesRequest(
        scope=_scope(),
        compatibility=_compatibility(),
        page=PageRequest(limit=50),
        updated_since=NOW - timedelta(hours=1),
    )
    first = provider_request_identity(request)
    second = provider_request_identity(request)
    changed = provider_request_identity(
        CurrentSeasonFixturesRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            page=PageRequest(limit=50, cursor="next"),
            updated_since=NOW - timedelta(hours=1),
        )
    )
    key = deterministic_provider_cache_key(
        source_id=SOURCE,
        capability=request.capability,
        request_identity_sha256=first.sha256,
        fetched_at=NOW,
    )

    assert first == second
    assert first.sha256 != changed.sha256
    assert b"credential" not in first.payload and b"url" not in first.payload
    assert len(key) == 64
    assert PROVIDER_CACHE_CAPABILITY_BY_OPERATION[request.capability].value == (
        "fixtures"
    )
    assert (
        PROVIDER_CACHE_CAPABILITY_BY_OPERATION[CurrentProviderCapability.TEAMS].value
        == "metadata"
    )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        deterministic_provider_cache_key(
            source_id=SOURCE,
            capability=request.capability,
            request_identity_sha256="invalid",
            fetched_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        deterministic_provider_cache_key(
            source_id=SOURCE,
            capability=request.capability,
            request_identity_sha256=first.sha256,
            fetched_at=datetime(2026, 9, 13, 12),
        )


def test_request_boundaries_reject_unsafe_time_and_fixture_order() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        CurrentSeasonFixturesRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            updated_since=datetime(2026, 9, 13, 12),
        )
    with pytest.raises(ValidationError, match="unique and ordered"):
        FixtureStatusRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            fixture_ids=(_provider_fixture("b"), _provider_fixture("a")),
        )
    with pytest.raises(ValidationError, match="request source"):
        FixtureStatusRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            fixture_ids=(_provider_fixture("a", "other"),),
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        CompletedResultsRequest(
            scope=_scope(),
            compatibility=_compatibility(),
            completed_since=datetime(2026, 9, 13, 12),
        )


def test_exact_response_and_capture_preserve_bytes_checksums_and_compatibility() -> (
    None
):
    exact = _exact_response()
    capture = _capture(CurrentProviderCapability.TEAMS, item_count=0)

    assert exact.body.endswith(b"\n")
    assert capture.response.sha256 == hashlib.sha256(capture.response.body).hexdigest()
    assert capture.compatibility.format_id.startswith("current-provider-v1")
    assert capture.cache_capability.value == "metadata"

    with pytest.raises(ValidationError, match="checksum"):
        ExactProviderResponse(
            body=b"changed",
            sha256="0" * 64,
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        )
    with pytest.raises(ValidationError, match="encoding"):
        ExactProviderResponse(
            body=b"\xff",
            sha256=hashlib.sha256(b"\xff").hexdigest(),
            http_status=200,
            media_type="application/json",
            encoding="utf-8",
        )
    with pytest.raises(ValidationError, match="canonical"):
        ProviderRequestIdentity(
            payload=b'{"z":1, "a":2}',
            sha256=hashlib.sha256(b'{"z":1, "a":2}').hexdigest(),
        )

    future_payload = capture.model_dump()
    future_payload["provider_generated_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="cannot follow retrieval"):
        ProviderResponseCapture.model_validate(future_payload)

    mismatch_payload = capture.model_dump()
    mismatch_payload["capability"] = CurrentProviderCapability.STANDINGS
    with pytest.raises(ValidationError, match="request identity capability"):
        ProviderResponseCapture.model_validate(mismatch_payload)


def test_all_typed_response_envelopes_validate_order_scope_and_knowledge_time() -> None:
    home = _provider_team("home")
    away = _provider_team("away")
    kickoff = ProviderKickoff(
        kickoff_at=datetime(2026, 9, 14, 14, tzinfo=UTC),
        precision=KickoffPrecision.EXACT,
        source_timezone="Europe/London",
        source_local_date=date(2026, 9, 14),
    )
    teams = (
        CurrentSeasonTeam(provider_team_id=away, provider_name="Away"),
        CurrentSeasonTeam(provider_team_id=home, provider_name="Home"),
    )
    fixtures = (
        CurrentSeasonFixture(
            provider_fixture_id=_provider_fixture("fixture-1"),
            home_provider_team_id=home,
            away_provider_team_id=away,
            kickoff=kickoff,
            status=FixtureStatus.SCHEDULED,
            provider_updated_at=NOW,
        ),
    )
    statuses = (
        FixtureStatusObservation(
            provider_fixture_id=_provider_fixture("fixture-1"),
            status=FixtureStatus.SCHEDULED,
            observed_at=NOW,
        ),
    )
    results = (
        CompletedFixtureResult(
            provider_fixture_id=_provider_fixture("fixture-1"),
            home_provider_team_id=home,
            away_provider_team_id=away,
            full_time_score=FixtureScore(home=1, away=0),
            outcome=MatchOutcome.HOME_WIN,
            completed_at=NOW,
        ),
    )
    standing_rows = (
        StandingRow(
            provider_team_id=home,
            position=1,
            played=1,
            won=1,
            drawn=0,
            lost=0,
            goals_for=1,
            goals_against=0,
            goal_difference=1,
            points=3,
        ),
        StandingRow(
            provider_team_id=away,
            position=2,
            played=1,
            won=0,
            drawn=0,
            lost=1,
            goals_for=0,
            goals_against=1,
            goal_difference=-1,
            points=0,
        ),
    )

    assert (
        len(
            CurrentSeasonTeamsResponse(
                scope=_scope(),
                items=teams,
                capture=_capture(CurrentProviderCapability.TEAMS, item_count=2),
            ).items
        )
        == 2
    )
    assert (
        len(
            CurrentSeasonFixturesResponse(
                scope=_scope(),
                items=fixtures,
                capture=_capture(CurrentProviderCapability.FIXTURES, item_count=1),
            ).items
        )
        == 1
    )
    assert (
        len(
            FixtureStatusResponse(
                scope=_scope(),
                items=statuses,
                capture=_capture(
                    CurrentProviderCapability.FIXTURE_STATUS, item_count=1
                ),
            ).items
        )
        == 1
    )
    assert (
        len(
            CompletedResultsResponse(
                scope=_scope(),
                items=results,
                capture=_capture(
                    CurrentProviderCapability.COMPLETED_RESULTS,
                    item_count=1,
                ),
            ).items
        )
        == 1
    )
    assert (
        len(
            StandingsResponse(
                scope=_scope(),
                items=standing_rows,
                capture=_capture(CurrentProviderCapability.STANDINGS, item_count=2),
            ).items
        )
        == 2
    )

    with pytest.raises(ValidationError, match="unique and ordered"):
        CurrentSeasonTeamsResponse(
            scope=_scope(),
            items=tuple(reversed(teams)),
            capture=_capture(CurrentProviderCapability.TEAMS, item_count=2),
        )
    with pytest.raises(ValidationError, match="pagination metadata"):
        CurrentSeasonTeamsResponse(
            scope=_scope(),
            items=teams,
            capture=_capture(CurrentProviderCapability.TEAMS, item_count=1),
        )
    future_fixture = CurrentSeasonFixture.model_validate(
        {
            **fixtures[0].model_dump(),
            "provider_updated_at": NOW + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValidationError, match="cannot follow response retrieval"):
        CurrentSeasonFixturesResponse(
            scope=_scope(),
            items=(future_fixture,),
            capture=_capture(CurrentProviderCapability.FIXTURES, item_count=1),
        )


def test_provider_errors_are_sanitized_and_retry_metadata_is_typed() -> None:
    permanent = ProviderError(
        source_id=SOURCE,
        capability=CurrentProviderCapability.TEAMS,
        code=ProviderErrorCode.UNKNOWN_CANONICAL_IDENTITY,
        retry_disposition=RetryDisposition.NEVER,
        occurred_at=NOW,
        safe_message="unknown canonical team identity",
    )
    wrapped = ProviderOperationError(permanent)

    assert str(wrapped) == "unknown canonical team identity"
    assert wrapped.detail is permanent
    with pytest.raises(ValidationError, match="requires a delay"):
        ProviderError.model_validate(
            {
                **permanent.model_dump(),
                "code": ProviderErrorCode.TIMEOUT,
                "retry_disposition": RetryDisposition.RETRY_AFTER,
            }
        )
    with pytest.raises(ValidationError, match="permanent provider error"):
        ProviderError.model_validate(
            {
                **permanent.model_dump(),
                "retry_disposition": RetryDisposition.RETRY_LATER,
            }
        )
    with pytest.raises(ValidationError, match="exhausted quota"):
        ProviderError.model_validate(
            {
                **permanent.model_dump(),
                "code": ProviderErrorCode.QUOTA_EXHAUSTED,
                "retry_disposition": RetryDisposition.AFTER_QUOTA_RESET,
            }
        )

    quota = QuotaMetadata(
        status=QuotaStatus.EXHAUSTED,
        limit=10,
        remaining=0,
        resets_at=NOW + timedelta(hours=1),
    )
    recoverable = ProviderError(
        source_id=SOURCE,
        capability=CurrentProviderCapability.FIXTURES,
        code=ProviderErrorCode.QUOTA_EXHAUSTED,
        retry_disposition=RetryDisposition.AFTER_QUOTA_RESET,
        occurred_at=NOW,
        safe_message="provider quota exhausted",
        quota=quota,
    )
    assert recoverable.quota == quota


def test_manifest_and_error_times_require_utc_not_other_offsets() -> None:
    non_utc = datetime(2026, 9, 13, 13, tzinfo=timezone(timedelta(hours=1)))
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ProviderCapabilityManifest(
            source_id=SOURCE,
            observed_at=non_utc,
            compatibility=_compatibility(),
            capabilities=_declarations(),
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ProviderError(
            source_id=SOURCE,
            capability=CurrentProviderCapability.TEAMS,
            code=ProviderErrorCode.TIMEOUT,
            retry_disposition=RetryDisposition.RETRY_LATER,
            occurred_at=non_utc,
            safe_message="timeout",
        )
