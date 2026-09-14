"""Provider-neutral HTTPS execution, authentication, quota and retry policy."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from http.client import HTTPResponse
from threading import Lock
from typing import Annotated, Literal, Protocol, Self
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    ExactProviderResponse,
    PageMetadata,
    ProviderCompatibility,
    ProviderError,
    ProviderErrorCode,
    ProviderOperationError,
    ProviderRequestIdentity,
    ProviderResponseCapture,
    QuotaMetadata,
    QuotaStatus,
    RetryDisposition,
)

_HEADER_NAME_PATTERN = r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$"
_SENSITIVE_QUERY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)
_SENSITIVE_HEADER_PARTS = (
    "api-key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)


class PublicProviderHeader(BaseModel):
    """Non-secret header safe to retain in an in-memory request specification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=_HEADER_NAME_PATTERN)
    value: str = Field(min_length=1)

    @model_validator(mode="after")
    def header_must_be_public_and_single_line(self) -> Self:
        lowered = self.name.casefold()
        if any(part in lowered for part in _SENSITIVE_HEADER_PARTS):
            raise ValueError("authentication headers must use the secret contract")
        if any(
            ord(character) < 32 or ord(character) == 127 for character in self.value
        ):
            raise ValueError("provider header values must be single-line")
        return self


class ProviderAuthentication(BaseModel):
    """Secret header authentication that stays outside request identity and logs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header_name: str = Field(pattern=_HEADER_NAME_PATTERN)
    credential: SecretStr
    value_prefix: str = ""

    @model_validator(mode="after")
    def authentication_must_be_safe(self) -> Self:
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in self.value_prefix
        ):
            raise ValueError("authentication prefix must be single-line")
        credential = self.credential.get_secret_value()
        if not credential or any(
            ord(character) < 32 or ord(character) == 127 for character in credential
        ):
            raise ValueError(
                "authentication credential must be nonempty and single-line"
            )
        return self

    def header(self) -> tuple[str, str]:
        return self.header_name, self.value_prefix + self.credential.get_secret_value()


class ProviderEndpointRequest(BaseModel):
    """One credential-free HTTPS request specification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_.-]*[a-z0-9])?$")
    capability: CurrentProviderCapability
    request_identity: ProviderRequestIdentity
    url: str = Field(min_length=1)
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    headers: tuple[PublicProviderHeader, ...] = ()
    timeout_seconds: Annotated[float, Field(strict=True, gt=0, le=60)] = 10.0
    max_response_bytes: Annotated[int, Field(strict=True, ge=1, le=50_000_000)] = (
        5_000_000
    )
    method: Literal["GET"] = "GET"

    @model_validator(mode="after")
    def endpoint_must_be_https_allowlisted_and_credential_free(self) -> Self:
        if any(ord(character) < 32 or ord(character) == 127 for character in self.url):
            raise ValueError("provider endpoint cannot contain control characters")
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("provider endpoint must be credential-free HTTPS")
        normalized_hosts = tuple(host.casefold() for host in self.allowed_hosts)
        if normalized_hosts != tuple(sorted(set(normalized_hosts))):
            raise ValueError("provider allowed hosts must be unique and ordered")
        if parsed.hostname.casefold() not in normalized_hosts:
            raise ValueError("provider endpoint host is not allowlisted")
        for name, _ in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = name.casefold()
            if any(part in lowered for part in _SENSITIVE_QUERY_PARTS):
                raise ValueError("provider credentials are prohibited in endpoint URLs")
        header_names = tuple(header.name.casefold() for header in self.headers)
        if len(header_names) != len(set(header_names)):
            raise ValueError("provider request headers must be unique")
        identity = json.loads(self.request_identity.payload.decode("utf-8"))
        scope = identity.get("scope")
        provider_competition = (
            scope.get("provider_competition_id") if isinstance(scope, dict) else None
        )
        identity_source = (
            provider_competition.get("source_id")
            if isinstance(provider_competition, dict)
            else None
        )
        if identity.get("capability") != self.capability.value:
            raise ValueError("endpoint capability does not match request identity")
        if identity_source != self.source_id:
            raise ValueError("endpoint source does not match request identity")
        return self


@dataclass(frozen=True, slots=True)
class PreparedProviderRequest:
    url: str
    method: Literal["GET"]
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int


@dataclass(frozen=True, slots=True)
class ProviderTransportResponse:
    body: bytes
    http_status: int
    media_type: str
    encoding: str | None
    etag: str | None = None
    last_modified: str | None = None
    provider_request_id: str | None = None
    quota: QuotaMetadata = field(
        default_factory=lambda: QuotaMetadata(status=QuotaStatus.UNKNOWN)
    )
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if not 100 <= self.http_status <= 599:
            raise ValueError("provider HTTP status is outside the valid range")
        if not self.media_type:
            raise ValueError("provider response media type cannot be empty")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 1:
            raise ValueError("provider retry delay must be positive")


class ProviderTransportFailure(RuntimeError):
    """Sanitized transport failure that never includes a URL or credential."""

    def __init__(self, code: ProviderErrorCode, safe_message: str) -> None:
        if code not in {
            ProviderErrorCode.TIMEOUT,
            ProviderErrorCode.TRANSPORT_FAILURE,
            ProviderErrorCode.MALFORMED_RESPONSE,
        }:
            raise ValueError("invalid transport failure code")
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class ProviderTransport(Protocol):
    def send(self, request: PreparedProviderRequest) -> ProviderTransportResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        return None


class UrllibProviderTransport:
    """Small synchronous HTTPS transport with redirects disabled."""

    def __init__(self, opener: OpenerDirector | None = None) -> None:
        self._opener = opener or build_opener(_NoRedirectHandler())

    def send(self, request: PreparedProviderRequest) -> ProviderTransportResponse:
        wire_request = Request(
            request.url,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with self._opener.open(
                wire_request,
                timeout=request.timeout_seconds,
            ) as response:
                return self._read_response(response, request.max_response_bytes)
        except HTTPError as exc:
            return self._read_response(exc, request.max_response_bytes)
        except TimeoutError as exc:
            raise ProviderTransportFailure(
                ProviderErrorCode.TIMEOUT,
                "current-provider request timed out",
            ) from exc
        except (URLError, OSError) as exc:
            raise ProviderTransportFailure(
                ProviderErrorCode.TRANSPORT_FAILURE,
                "current-provider transport failed",
            ) from exc

    @staticmethod
    def _read_response(
        response: HTTPResponse | HTTPError, maximum_bytes: int
    ) -> ProviderTransportResponse:
        body = response.read(maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise ProviderTransportFailure(
                ProviderErrorCode.MALFORMED_RESPONSE,
                "current-provider response exceeds the configured byte limit",
            )
        status = (
            response.status if isinstance(response, HTTPResponse) else response.code
        )
        headers = response.headers
        content_type = headers.get("Content-Type", "application/octet-stream")
        media_type = content_type.split(";", maxsplit=1)[0].strip().casefold()
        encoding = (
            headers.get_content_charset()
            if hasattr(headers, "get_content_charset")
            else None
        )
        if encoding is not None:
            encoding = encoding.casefold().replace("utf8", "utf-8")
        retry_after = headers.get("Retry-After")
        return ProviderTransportResponse(
            body=body,
            http_status=status,
            media_type=media_type,
            encoding=encoding,
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
            provider_request_id=headers.get("X-Request-ID"),
            retry_after_seconds=(
                int(retry_after)
                if retry_after is not None and retry_after.isdigit()
                else None
            ),
        )


class ProviderRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    maximum_attempts: Annotated[int, Field(strict=True, ge=1, le=5)] = 3
    base_delay_seconds: Annotated[float, Field(strict=True, ge=0, le=60)] = 1.0
    maximum_delay_seconds: Annotated[float, Field(strict=True, ge=0, le=300)] = 30.0

    def delay_for(self, attempt: int, retry_after_seconds: int | None) -> float:
        if retry_after_seconds is not None:
            return min(float(retry_after_seconds), self.maximum_delay_seconds)
        return min(
            self.base_delay_seconds * pow(2.0, attempt - 1),
            self.maximum_delay_seconds,
        )


@dataclass(frozen=True, slots=True)
class _QuotaObservation:
    metadata: QuotaMetadata
    observed_at: datetime


class ProviderQuotaLedger:
    """Process-local conservative quota state keyed by provider capability."""

    def __init__(self) -> None:
        self._observations: dict[
            tuple[str, CurrentProviderCapability], _QuotaObservation
        ] = {}
        self._lock = Lock()

    def record(
        self,
        source_id: str,
        capability: CurrentProviderCapability,
        quota: QuotaMetadata,
        observed_at: datetime,
    ) -> None:
        with self._lock:
            self._observations[(source_id, capability)] = _QuotaObservation(
                quota, observed_at
            )

    def require_available(
        self,
        request: ProviderEndpointRequest,
        now: datetime,
    ) -> None:
        with self._lock:
            observation = self._observations.get(
                (request.source_id, request.capability)
            )
            if (
                observation is None
                or observation.metadata.status is not QuotaStatus.EXHAUSTED
            ):
                return
            quota = observation.metadata
            boundaries = tuple(
                boundary
                for boundary in (
                    quota.resets_at,
                    (
                        observation.observed_at
                        + timedelta(seconds=quota.retry_after_seconds)
                        if quota.retry_after_seconds is not None
                        else None
                    ),
                )
                if boundary is not None
            )
            if boundaries and now >= max(boundaries):
                del self._observations[(request.source_id, request.capability)]
                return
        raise ProviderOperationError(
            ProviderError(
                source_id=request.source_id,
                capability=request.capability,
                code=ProviderErrorCode.QUOTA_EXHAUSTED,
                retry_disposition=RetryDisposition.AFTER_QUOTA_RESET,
                occurred_at=now,
                safe_message="current-provider quota is exhausted",
                request_identity_sha256=request.request_identity.sha256,
                quota=quota,
            )
        )


class CurrentProviderRequestExecutor:
    """Execute one provider request with bounded retries and sanitized logs."""

    def __init__(
        self,
        transport: ProviderTransport,
        *,
        authentication: ProviderAuthentication | None = None,
        retry_policy: ProviderRetryPolicy | None = None,
        quota_ledger: ProviderQuotaLedger | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._transport = transport
        self._authentication = authentication
        self._retry_policy = retry_policy or ProviderRetryPolicy()
        self._quota_ledger = quota_ledger or ProviderQuotaLedger()
        self._sleeper = sleeper
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: ProviderEndpointRequest) -> ProviderTransportResponse:
        now = self._clock()
        self._quota_ledger.require_available(request, now)
        headers = [(item.name, item.value) for item in request.headers]
        if self._authentication is not None:
            auth_header = self._authentication.header()
            if any(name.casefold() == auth_header[0].casefold() for name, _ in headers):
                raise ValueError("authentication header duplicates a public header")
            headers.append(auth_header)
        prepared = PreparedProviderRequest(
            url=request.url,
            method=request.method,
            headers=tuple(headers),
            timeout_seconds=request.timeout_seconds,
            max_response_bytes=request.max_response_bytes,
        )

        for attempt in range(1, self._retry_policy.maximum_attempts + 1):
            try:
                response = self._transport.send(prepared)
            except ProviderTransportFailure as exc:
                error = self._transport_error(request, exc, self._clock())
            else:
                observed_at = self._clock()
                self._quota_ledger.record(
                    request.source_id,
                    request.capability,
                    response.quota,
                    observed_at,
                )
                if 200 <= response.http_status <= 299:
                    return response
                error = self._response_error(request, response, observed_at)

            if (
                not self._retryable(error)
                or attempt == self._retry_policy.maximum_attempts
            ):
                self._log_failure(request, error, attempt, will_retry=False)
                raise ProviderOperationError(error)
            delay = self._retry_policy.delay_for(
                attempt,
                error.retry_after_seconds,
            )
            self._log_failure(request, error, attempt, will_retry=True)
            self._sleeper(delay)
        raise AssertionError("bounded provider attempt loop did not terminate")

    @staticmethod
    def _retryable(error: ProviderError) -> bool:
        return error.retry_disposition in {
            RetryDisposition.RETRY_LATER,
            RetryDisposition.RETRY_AFTER,
        }

    def _log_failure(
        self,
        request: ProviderEndpointRequest,
        error: ProviderError,
        attempt: int,
        *,
        will_retry: bool,
    ) -> None:
        self._logger.warning(
            "current-provider request failed",
            extra={
                "attempt": attempt,
                "capability": request.capability.value,
                "error_code": error.code.value,
                "request_identity_sha256": request.request_identity.sha256,
                "retry_disposition": error.retry_disposition.value,
                "source_id": request.source_id,
                "will_retry": will_retry,
            },
        )

    @staticmethod
    def _transport_error(
        request: ProviderEndpointRequest,
        failure: ProviderTransportFailure,
        occurred_at: datetime,
    ) -> ProviderError:
        return ProviderError(
            source_id=request.source_id,
            capability=request.capability,
            code=failure.code,
            retry_disposition=RetryDisposition.RETRY_LATER,
            occurred_at=occurred_at,
            safe_message=failure.safe_message,
            request_identity_sha256=request.request_identity.sha256,
        )

    @staticmethod
    def _response_error(
        request: ProviderEndpointRequest,
        response: ProviderTransportResponse,
        occurred_at: datetime,
    ) -> ProviderError:
        status = response.http_status
        if status == 400:
            code = ProviderErrorCode.INVALID_REQUEST
            disposition = RetryDisposition.NEVER
        elif status == 401:
            code = ProviderErrorCode.AUTHENTICATION_FAILED
            disposition = RetryDisposition.NEVER
        elif status == 403:
            code = ProviderErrorCode.PERMISSION_DENIED
            disposition = RetryDisposition.NEVER
        elif status == 404:
            code = ProviderErrorCode.NOT_FOUND
            disposition = RetryDisposition.NEVER
        elif status == 408:
            code = ProviderErrorCode.TIMEOUT
            disposition = RetryDisposition.RETRY_LATER
        elif status == 429 and response.quota.status is QuotaStatus.EXHAUSTED:
            code = ProviderErrorCode.QUOTA_EXHAUSTED
            disposition = RetryDisposition.AFTER_QUOTA_RESET
        elif status == 429:
            code = ProviderErrorCode.RATE_LIMITED
            disposition = (
                RetryDisposition.RETRY_AFTER
                if response.retry_after_seconds is not None
                else RetryDisposition.RETRY_LATER
            )
        elif 500 <= status <= 599:
            code = ProviderErrorCode.TEMPORARILY_UNAVAILABLE
            disposition = RetryDisposition.RETRY_LATER
        else:
            code = ProviderErrorCode.PROVIDER_REJECTED
            disposition = RetryDisposition.NEVER
        return ProviderError(
            source_id=request.source_id,
            capability=request.capability,
            code=code,
            retry_disposition=disposition,
            occurred_at=occurred_at,
            safe_message="current-provider request was not successful",
            http_status=status,
            request_identity_sha256=request.request_identity.sha256,
            provider_request_id=response.provider_request_id,
            retry_after_seconds=(
                response.retry_after_seconds
                if disposition is RetryDisposition.RETRY_AFTER
                else None
            ),
            quota=response.quota,
        )


def capture_successful_transport_response(
    request: ProviderEndpointRequest,
    response: ProviderTransportResponse,
    *,
    retrieved_at: datetime,
    compatibility: ProviderCompatibility,
    page: PageMetadata,
    provider_generated_at: datetime | None = None,
) -> ProviderResponseCapture:
    """Build the exact-byte capture consumed by typed parsers and the cache."""

    exact = ExactProviderResponse.model_validate(
        {
            "body": response.body,
            "sha256": hashlib.sha256(response.body).hexdigest(),
            "http_status": response.http_status,
            "media_type": response.media_type,
            "encoding": response.encoding,
            "etag": response.etag,
            "last_modified": response.last_modified,
        }
    )
    return ProviderResponseCapture(
        source_id=request.source_id,
        capability=request.capability,
        request_identity=request.request_identity,
        retrieved_at=retrieved_at,
        provider_generated_at=provider_generated_at,
        provider_request_id=response.provider_request_id,
        compatibility=compatibility,
        page=page,
        quota=response.quota,
        response=exact,
    )
