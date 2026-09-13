"""Strict provider-neutral capability boundary for current-season ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.current import (
    CompletedFixtureResult,
    CurrentSeasonFixture,
    CurrentSeasonScope,
    CurrentSeasonTeam,
    FixtureStatusObservation,
    ProviderFixtureIdentifier,
    StandingRow,
)

CURRENT_PROVIDER_CONTRACT_VERSION: Final = 1
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_.-]*[a-z0-9])?$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


def _must_be_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _utc_text(value: datetime) -> str:
    _must_be_utc(value, "timestamp")
    return value.isoformat().replace("+00:00", "Z")


class CurrentProviderCapability(StrEnum):
    TEAMS = "current_season_teams"
    FIXTURES = "current_season_fixtures"
    FIXTURE_STATUS = "fixture_status"
    COMPLETED_RESULTS = "completed_results"
    STANDINGS = "standings"


CAPABILITY_ORDER: Final[tuple[CurrentProviderCapability, ...]] = tuple(
    CurrentProviderCapability
)


class CapabilityAvailability(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class CapabilityRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


CAPABILITY_REQUIREMENTS: Final[
    Mapping[CurrentProviderCapability, CapabilityRequirement]
] = MappingProxyType(
    {
        CurrentProviderCapability.TEAMS: CapabilityRequirement.REQUIRED,
        CurrentProviderCapability.FIXTURES: CapabilityRequirement.REQUIRED,
        CurrentProviderCapability.FIXTURE_STATUS: CapabilityRequirement.REQUIRED,
        CurrentProviderCapability.COMPLETED_RESULTS: CapabilityRequirement.REQUIRED,
        CurrentProviderCapability.STANDINGS: CapabilityRequirement.OPTIONAL,
    }
)


class IdentityResolutionContract(BaseModel):
    """Fail-closed identity policy shared by every provider capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_resolution: Literal["reviewed_alias_or_external_id_only"] = (
        "reviewed_alias_or_external_id_only"
    )
    unknown_identity_policy: Literal["reject"] = "reject"
    fuzzy_matching_policy: Literal["prohibited"] = "prohibited"
    provider_id_as_canonical_policy: Literal["prohibited"] = "prohibited"


class ProviderCompatibility(BaseModel):
    """Versions required to interpret a request and its exact response bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal[1] = CURRENT_PROVIDER_CONTRACT_VERSION
    provider_api_version: Identifier
    parser_schema_version: Identifier
    response_contract_version: Literal[1] = CURRENT_PROVIDER_CONTRACT_VERSION
    identity_resolution: IdentityResolutionContract = IdentityResolutionContract()

    @property
    def format_id(self) -> str:
        return (
            f"current-provider-v{self.contract_version}."
            f"{self.provider_api_version}.{self.parser_schema_version}"
        )


class CapabilityDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: CurrentProviderCapability
    availability: CapabilityAvailability
    requirement: CapabilityRequirement
    supports_pagination: bool
    maximum_page_size: PositiveInt | None = None
    reason: str | None = Field(default=None, min_length=1)
    retry_after_seconds: PositiveInt | None = None

    @model_validator(mode="after")
    def availability_metadata_must_be_consistent(self) -> Self:
        if self.availability is CapabilityAvailability.SUPPORTED:
            if self.reason is not None or self.retry_after_seconds is not None:
                raise ValueError("supported capability cannot declare unavailability")
        elif self.reason is None:
            raise ValueError("unavailable capability requires a reason")
        if self.availability is CapabilityAvailability.UNSUPPORTED:
            if self.supports_pagination or self.maximum_page_size is not None:
                raise ValueError("unsupported capability cannot declare pagination")
            if self.retry_after_seconds is not None:
                raise ValueError("unsupported capability cannot declare retry timing")
        if not self.supports_pagination and self.maximum_page_size is not None:
            raise ValueError("non-paginated capability cannot declare a page size")
        return self


class ProviderCapabilityManifest(BaseModel):
    """Complete point-in-time declaration for one otherwise unspecified provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = CURRENT_PROVIDER_CONTRACT_VERSION
    source_id: Identifier
    observed_at: datetime
    compatibility: ProviderCompatibility
    capabilities: tuple[CapabilityDeclaration, ...]

    @model_validator(mode="after")
    def manifest_must_be_complete_and_ordered(self) -> Self:
        _must_be_utc(self.observed_at, "observed_at")
        actual = tuple(item.capability for item in self.capabilities)
        if actual != CAPABILITY_ORDER:
            raise ValueError(
                "capability manifest must be complete and canonically ordered"
            )
        for item in self.capabilities:
            if item.requirement is not CAPABILITY_REQUIREMENTS[item.capability]:
                raise ValueError(
                    "capability requirement does not match platform policy"
                )
        return self


class PageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: Annotated[int, Field(strict=True, ge=1, le=1000)] = 100
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class PageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    returned_count: NonNegativeInt
    has_more: bool
    next_cursor: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def cursor_state_must_be_consistent(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more and next_cursor must agree")
        if self.next_cursor is not None and self.next_cursor == self.request_cursor:
            raise ValueError("pagination cursor did not advance")
        return self


class QuotaStatus(StrEnum):
    UNKNOWN = "unknown"
    UNLIMITED = "unlimited"
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"


class QuotaMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: QuotaStatus
    bucket: str | None = Field(default=None, min_length=1)
    limit: NonNegativeInt | None = None
    remaining: NonNegativeInt | None = None
    resets_at: datetime | None = None
    retry_after_seconds: PositiveInt | None = None

    @model_validator(mode="after")
    def quota_state_must_be_consistent(self) -> Self:
        if self.resets_at is not None:
            _must_be_utc(self.resets_at, "resets_at")
        values = (self.limit, self.remaining, self.resets_at, self.retry_after_seconds)
        if self.status in {QuotaStatus.UNKNOWN, QuotaStatus.UNLIMITED}:
            if any(value is not None for value in values):
                raise ValueError("unknown or unlimited quota cannot declare limits")
            return self
        if self.limit is None or self.remaining is None:
            raise ValueError("bounded quota requires limit and remaining")
        if self.remaining > self.limit:
            raise ValueError("quota remaining cannot exceed limit")
        if self.status is QuotaStatus.AVAILABLE and self.remaining == 0:
            raise ValueError("available quota must have remaining requests")
        if self.status is QuotaStatus.EXHAUSTED:
            if self.remaining != 0:
                raise ValueError("exhausted quota must have zero remaining")
            if self.resets_at is None and self.retry_after_seconds is None:
                raise ValueError("exhausted quota requires reset or retry metadata")
        return self


class _SeasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = CURRENT_PROVIDER_CONTRACT_VERSION
    scope: CurrentSeasonScope
    compatibility: ProviderCompatibility
    page: PageRequest = PageRequest()


class CurrentSeasonTeamsRequest(_SeasonRequest):
    capability: Literal[CurrentProviderCapability.TEAMS] = (
        CurrentProviderCapability.TEAMS
    )


class CurrentSeasonFixturesRequest(_SeasonRequest):
    capability: Literal[CurrentProviderCapability.FIXTURES] = (
        CurrentProviderCapability.FIXTURES
    )
    updated_since: datetime | None = None

    @model_validator(mode="after")
    def update_boundary_must_be_utc(self) -> Self:
        if self.updated_since is not None:
            _must_be_utc(self.updated_since, "updated_since")
        return self


class FixtureStatusRequest(_SeasonRequest):
    capability: Literal[CurrentProviderCapability.FIXTURE_STATUS] = (
        CurrentProviderCapability.FIXTURE_STATUS
    )
    fixture_ids: tuple[ProviderFixtureIdentifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fixture_ids_must_be_unique_ordered_and_scoped(self) -> Self:
        if any(item.source_id != self.scope.source_id for item in self.fixture_ids):
            raise ValueError("fixture-status identifiers do not match request source")
        keys = tuple(item.external_id for item in self.fixture_ids)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("fixture-status identifiers must be unique and ordered")
        return self


class CompletedResultsRequest(_SeasonRequest):
    capability: Literal[CurrentProviderCapability.COMPLETED_RESULTS] = (
        CurrentProviderCapability.COMPLETED_RESULTS
    )
    completed_since: datetime | None = None

    @model_validator(mode="after")
    def completion_boundary_must_be_utc(self) -> Self:
        if self.completed_since is not None:
            _must_be_utc(self.completed_since, "completed_since")
        return self


class StandingsRequest(_SeasonRequest):
    capability: Literal[CurrentProviderCapability.STANDINGS] = (
        CurrentProviderCapability.STANDINGS
    )


type CurrentProviderRequest = (
    CurrentSeasonTeamsRequest
    | CurrentSeasonFixturesRequest
    | FixtureStatusRequest
    | CompletedResultsRequest
    | StandingsRequest
)


class ProviderRequestIdentity(BaseModel):
    """Exact canonical request bytes and their content identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: bytes = Field(min_length=1)
    sha256: Sha256

    @model_validator(mode="after")
    def checksum_must_match_payload(self) -> Self:
        if hashlib.sha256(self.payload).hexdigest() != self.sha256:
            raise ValueError("request identity checksum does not match exact bytes")
        try:
            parsed = json.loads(self.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request identity must be valid UTF-8 JSON") from exc
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not isinstance(parsed, dict) or canonical != self.payload:
            raise ValueError("request identity bytes are not canonical")
        return self


def provider_request_identity(
    request: CurrentProviderRequest,
) -> ProviderRequestIdentity:
    """Create compact sorted UTF-8 identity bytes without credentials or URLs."""

    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ProviderRequestIdentity(
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


class ProviderCacheCapability(StrEnum):
    FIXTURES = "fixtures"
    RESULTS = "results"
    STANDINGS = "standings"
    METADATA = "metadata"


PROVIDER_CACHE_CAPABILITY_BY_OPERATION: Final[
    Mapping[CurrentProviderCapability, ProviderCacheCapability]
] = MappingProxyType(
    {
        CurrentProviderCapability.TEAMS: ProviderCacheCapability.METADATA,
        CurrentProviderCapability.FIXTURES: ProviderCacheCapability.FIXTURES,
        CurrentProviderCapability.FIXTURE_STATUS: ProviderCacheCapability.FIXTURES,
        CurrentProviderCapability.COMPLETED_RESULTS: ProviderCacheCapability.RESULTS,
        CurrentProviderCapability.STANDINGS: ProviderCacheCapability.STANDINGS,
    }
)


def deterministic_provider_cache_key(
    *,
    source_id: str,
    capability: CurrentProviderCapability,
    request_identity_sha256: str,
    fetched_at: datetime,
) -> str:
    """Return the content-derived key expected by the existing cache schema."""

    if len(request_identity_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in request_identity_sha256
    ):
        raise ValueError("request_identity_sha256 must be lowercase SHA-256")
    payload = json.dumps(
        {
            "cache_capability": PROVIDER_CACHE_CAPABILITY_BY_OPERATION[
                capability
            ].value,
            "fetched_at": _utc_text(fetched_at),
            "request_identity_sha256": request_identity_sha256,
            "schema_version": CURRENT_PROVIDER_CONTRACT_VERSION,
            "source_id": source_id,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ExactProviderResponse(BaseModel):
    """Exact provider bytes; parsed models never replace this evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    body: bytes = Field(min_length=1)
    sha256: Sha256
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)]
    media_type: str = Field(min_length=1)
    encoding: Literal["utf-8", "utf-8-sig", "cp1252"]
    etag: str | None = Field(default=None, min_length=1)
    last_modified: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def body_must_match_checksum_and_encoding(self) -> Self:
        if hashlib.sha256(self.body).hexdigest() != self.sha256:
            raise ValueError("response checksum does not match exact bytes")
        try:
            self.body.decode(self.encoding)
        except UnicodeDecodeError as exc:
            raise ValueError("response bytes do not match declared encoding") from exc
        return self


class ProviderResponseCapture(BaseModel):
    """Transport-neutral response metadata and complete exact-byte provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Identifier
    capability: CurrentProviderCapability
    request_identity: ProviderRequestIdentity
    retrieved_at: datetime
    provider_generated_at: datetime | None = None
    provider_request_id: str | None = Field(default=None, min_length=1)
    compatibility: ProviderCompatibility
    page: PageMetadata
    quota: QuotaMetadata
    response: ExactProviderResponse

    @model_validator(mode="after")
    def capture_timestamps_must_be_safe(self) -> Self:
        _must_be_utc(self.retrieved_at, "retrieved_at")
        if self.provider_generated_at is not None:
            _must_be_utc(self.provider_generated_at, "provider_generated_at")
            if self.provider_generated_at > self.retrieved_at:
                raise ValueError("provider timestamp cannot follow retrieval")
        if not 200 <= self.response.http_status <= 299:
            raise ValueError("typed success response requires a successful HTTP status")
        request = json.loads(self.request_identity.payload.decode("utf-8"))
        request_scope = request.get("scope")
        request_page = request.get("page")
        if not isinstance(request_scope, dict) or not isinstance(request_page, dict):
            raise ValueError("request identity does not contain the required boundary")
        request_provider_competition = request_scope.get("provider_competition_id")
        if not isinstance(request_provider_competition, dict):
            raise ValueError("request identity does not contain provider scope")
        request_source = request_provider_competition.get("source_id")
        if request.get("capability") != self.capability.value:
            raise ValueError("request identity capability does not match response")
        if request_source != self.source_id:
            raise ValueError("request identity source does not match response")
        if request.get("compatibility") != self.compatibility.model_dump(mode="json"):
            raise ValueError("request and response compatibility metadata differ")
        if request_page.get("cursor") != self.page.request_cursor:
            raise ValueError("response pagination does not match request identity")
        return self

    @property
    def cache_capability(self) -> ProviderCacheCapability:
        return PROVIDER_CACHE_CAPABILITY_BY_OPERATION[self.capability]


def _validate_response_boundary(
    *,
    scope: CurrentSeasonScope,
    capture: ProviderResponseCapture,
    expected_capability: CurrentProviderCapability,
    item_sources: tuple[str, ...],
    item_count: int,
) -> None:
    if capture.capability is not expected_capability:
        raise ValueError("response capability does not match its envelope")
    if capture.source_id != scope.source_id or any(
        source_id != scope.source_id for source_id in item_sources
    ):
        raise ValueError("response identifiers do not match its provider scope")
    if capture.page.returned_count != item_count:
        raise ValueError("response item count does not match pagination metadata")


class CurrentSeasonTeamsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CurrentSeasonScope
    items: tuple[CurrentSeasonTeam, ...]
    capture: ProviderResponseCapture

    @model_validator(mode="after")
    def response_must_be_ordered_and_scoped(self) -> Self:
        keys = tuple(item.provider_team_id.external_id for item in self.items)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("provider teams must be unique and ordered")
        _validate_response_boundary(
            scope=self.scope,
            capture=self.capture,
            expected_capability=CurrentProviderCapability.TEAMS,
            item_sources=tuple(item.provider_team_id.source_id for item in self.items),
            item_count=len(self.items),
        )
        return self


class CurrentSeasonFixturesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CurrentSeasonScope
    items: tuple[CurrentSeasonFixture, ...]
    capture: ProviderResponseCapture

    @model_validator(mode="after")
    def response_must_be_ordered_scoped_and_observed(self) -> Self:
        keys = tuple(
            (item.kickoff.kickoff_at, item.provider_fixture_id.external_id)
            for item in self.items
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("provider fixtures must be unique and ordered")
        for item in self.items:
            if (
                item.provider_updated_at is not None
                and item.provider_updated_at > self.capture.retrieved_at
            ):
                raise ValueError("fixture update cannot follow response retrieval")
        _validate_response_boundary(
            scope=self.scope,
            capture=self.capture,
            expected_capability=CurrentProviderCapability.FIXTURES,
            item_sources=tuple(
                item.provider_fixture_id.source_id for item in self.items
            ),
            item_count=len(self.items),
        )
        return self


class FixtureStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CurrentSeasonScope
    items: tuple[FixtureStatusObservation, ...]
    capture: ProviderResponseCapture

    @model_validator(mode="after")
    def response_must_be_ordered_scoped_and_observed(self) -> Self:
        keys = tuple(item.provider_fixture_id.external_id for item in self.items)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("fixture statuses must be unique and ordered")
        for item in self.items:
            if item.observed_at > self.capture.retrieved_at or (
                item.provider_updated_at is not None
                and item.provider_updated_at > self.capture.retrieved_at
            ):
                raise ValueError("fixture-status time cannot follow response retrieval")
        _validate_response_boundary(
            scope=self.scope,
            capture=self.capture,
            expected_capability=CurrentProviderCapability.FIXTURE_STATUS,
            item_sources=tuple(
                item.provider_fixture_id.source_id for item in self.items
            ),
            item_count=len(self.items),
        )
        return self


class CompletedResultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CurrentSeasonScope
    items: tuple[CompletedFixtureResult, ...]
    capture: ProviderResponseCapture

    @model_validator(mode="after")
    def response_must_be_ordered_scoped_and_observed(self) -> Self:
        keys = tuple(item.provider_fixture_id.external_id for item in self.items)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("completed results must be unique and ordered")
        for item in self.items:
            if (
                item.completed_at is not None
                and item.completed_at > self.capture.retrieved_at
            ):
                raise ValueError("completion time cannot follow response retrieval")
        _validate_response_boundary(
            scope=self.scope,
            capture=self.capture,
            expected_capability=CurrentProviderCapability.COMPLETED_RESULTS,
            item_sources=tuple(
                item.provider_fixture_id.source_id for item in self.items
            ),
            item_count=len(self.items),
        )
        return self


class StandingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CurrentSeasonScope
    items: tuple[StandingRow, ...]
    capture: ProviderResponseCapture

    @model_validator(mode="after")
    def response_must_be_ordered_and_scoped(self) -> Self:
        keys = tuple(
            (item.position, item.provider_team_id.external_id) for item in self.items
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("standing rows must have unique canonical order")
        team_ids = tuple(item.provider_team_id.external_id for item in self.items)
        positions = tuple(item.position for item in self.items)
        if len(team_ids) != len(set(team_ids)) or len(positions) != len(set(positions)):
            raise ValueError("standing teams and positions must be unique")
        _validate_response_boundary(
            scope=self.scope,
            capture=self.capture,
            expected_capability=CurrentProviderCapability.STANDINGS,
            item_sources=tuple(item.provider_team_id.source_id for item in self.items),
            item_count=len(self.items),
        )
        return self


class ProviderErrorCode(StrEnum):
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_PROVIDER_IDENTITY = "unknown_provider_identity"
    UNKNOWN_CANONICAL_IDENTITY = "unknown_canonical_identity"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    TRANSPORT_FAILURE = "transport_failure"
    PROVIDER_REJECTED = "provider_rejected"
    MALFORMED_RESPONSE = "malformed_response"
    INCOMPATIBLE_RESPONSE = "incompatible_response"
    RESPONSE_INTEGRITY_FAILURE = "response_integrity_failure"
    UNEXPECTED_PROVIDER_FAILURE = "unexpected_provider_failure"


class RetryDisposition(StrEnum):
    NEVER = "never"
    RETRY_LATER = "retry_later"
    RETRY_AFTER = "retry_after"
    AFTER_QUOTA_RESET = "after_quota_reset"


class ProviderError(BaseModel):
    """Sanitized provider failure; raw bodies, URLs and headers are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Identifier
    capability: CurrentProviderCapability
    code: ProviderErrorCode
    retry_disposition: RetryDisposition
    occurred_at: datetime
    safe_message: str = Field(min_length=1, max_length=512)
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None = None
    request_identity_sha256: Sha256 | None = None
    provider_request_id: str | None = Field(default=None, min_length=1)
    retry_after_seconds: PositiveInt | None = None
    quota: QuotaMetadata | None = None

    @model_validator(mode="after")
    def retry_metadata_must_be_consistent(self) -> Self:
        _must_be_utc(self.occurred_at, "occurred_at")
        if self.retry_disposition is RetryDisposition.RETRY_AFTER:
            if self.retry_after_seconds is None:
                raise ValueError("retry-after disposition requires a delay")
        elif self.retry_after_seconds is not None:
            raise ValueError("retry delay requires retry-after disposition")
        if self.retry_disposition is RetryDisposition.AFTER_QUOTA_RESET and (
            self.quota is None or self.quota.status is not QuotaStatus.EXHAUSTED
        ):
            raise ValueError("quota-reset disposition requires exhausted quota")
        if (
            self.code
            in {
                ProviderErrorCode.UNSUPPORTED_CAPABILITY,
                ProviderErrorCode.UNKNOWN_PROVIDER_IDENTITY,
                ProviderErrorCode.UNKNOWN_CANONICAL_IDENTITY,
            }
            and self.retry_disposition is not RetryDisposition.NEVER
        ):
            raise ValueError("permanent provider error cannot be retried")
        return self


class ProviderOperationError(RuntimeError):
    """Exception wrapper that exposes only the sanitized provider error contract."""

    def __init__(self, detail: ProviderError) -> None:
        self.detail = detail
        super().__init__(detail.safe_message)


class CurrentSeasonProvider(Protocol):
    """Provider-neutral port. Implementations begin in later numbered steps."""

    def describe_capabilities(self) -> ProviderCapabilityManifest: ...

    def get_current_season_teams(
        self, request: CurrentSeasonTeamsRequest
    ) -> CurrentSeasonTeamsResponse: ...

    def get_current_season_fixtures(
        self, request: CurrentSeasonFixturesRequest
    ) -> CurrentSeasonFixturesResponse: ...

    def get_fixture_statuses(
        self, request: FixtureStatusRequest
    ) -> FixtureStatusResponse: ...

    def get_completed_results(
        self, request: CompletedResultsRequest
    ) -> CompletedResultsResponse: ...

    def get_standings(self, request: StandingsRequest) -> StandingsResponse: ...
