"""Provider-neutral HTTPS, authentication, retry and quota tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from http.client import HTTPResponse
from typing import cast
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr, ValidationError

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    PageMetadata,
    ProviderErrorCode,
    ProviderOperationError,
    QuotaMetadata,
    QuotaStatus,
    provider_request_identity,
)
from pl_platform.ingestion.current_client import (
    CurrentProviderRequestExecutor,
    PreparedProviderRequest,
    ProviderAuthentication,
    ProviderEndpointRequest,
    ProviderRetryPolicy,
    ProviderTransportFailure,
    ProviderTransportResponse,
    PublicProviderHeader,
    UrllibProviderTransport,
    capture_successful_transport_response,
)
from tests.unit.ingestion.current_helpers import (
    NOW,
    SOURCE,
    compatibility,
    request_for,
)


def _endpoint(**changes: object) -> ProviderEndpointRequest:
    request = request_for(CurrentProviderCapability.FIXTURES)
    values: dict[str, object] = {
        "source_id": SOURCE,
        "capability": request.capability,
        "request_identity": provider_request_identity(request),
        "url": "https://api.example.test/fixtures?season=2026",
        "allowed_hosts": ("api.example.test",),
        "headers": (PublicProviderHeader(name="Accept", value="application/json"),),
    }
    return ProviderEndpointRequest.model_validate({**values, **changes})


class _ScriptedTransport:
    def __init__(
        self,
        outcomes: Iterator[ProviderTransportResponse | ProviderTransportFailure],
    ) -> None:
        self._outcomes = outcomes
        self.requests: list[PreparedProviderRequest] = []

    def send(self, request: PreparedProviderRequest) -> ProviderTransportResponse:
        self.requests.append(request)
        outcome = next(self._outcomes)
        if isinstance(outcome, ProviderTransportFailure):
            raise outcome
        return outcome


def _response(
    status: int = 200,
    *,
    quota: QuotaMetadata | None = None,
    retry_after_seconds: int | None = None,
) -> ProviderTransportResponse:
    return ProviderTransportResponse(
        body=b'{"ok":true}\n',
        http_status=status,
        media_type="application/json",
        encoding="utf-8",
        quota=quota or QuotaMetadata(status=QuotaStatus.UNKNOWN),
        retry_after_seconds=retry_after_seconds,
    )


def test_endpoint_rejects_unsafe_urls_headers_and_identity_mismatch() -> None:
    for changes in (
        {"url": "http://api.example.test/fixtures"},
        {"url": "https://other.example.test/fixtures"},
        {"url": "https://api.example.test/fixtures?api_key=secret"},
        {
            "headers": (
                PublicProviderHeader(name="Accept", value="application/json"),
                PublicProviderHeader(name="accept", value="text/plain"),
            )
        },
        {"source_id": "different-source"},
    ):
        with pytest.raises(ValidationError):
            _endpoint(**changes)
    with pytest.raises(ValidationError, match="secret contract"):
        PublicProviderHeader(name="Authorization", value="secret")
    with pytest.raises(ValidationError, match="single-line"):
        PublicProviderHeader(name="Accept", value="x\ny")


def test_executor_applies_secret_auth_retries_and_logs_only_safe_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _ScriptedTransport(iter((_response(503), _response())))
    delays: list[float] = []
    authentication = ProviderAuthentication(
        header_name="Authorization",
        credential=SecretStr("super-secret-token"),
        value_prefix="Bearer ",
    )
    executor = CurrentProviderRequestExecutor(
        transport,
        authentication=authentication,
        retry_policy=ProviderRetryPolicy(
            maximum_attempts=2,
            base_delay_seconds=0.25,
            maximum_delay_seconds=1.0,
        ),
        sleeper=delays.append,
        clock=lambda: NOW,
    )

    response = executor.execute(_endpoint())

    assert response.http_status == 200
    assert delays == [0.25]
    assert transport.requests[0].headers[-1] == (
        "Authorization",
        "Bearer super-secret-token",
    )
    assert "super-secret-token" not in caplog.text
    assert "https://" not in caplog.text
    assert caplog.records[0].__dict__["capability"] == "current_season_fixtures"
    assert "super-secret-token" not in repr(transport.requests[0])


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (400, ProviderErrorCode.INVALID_REQUEST),
        (401, ProviderErrorCode.AUTHENTICATION_FAILED),
        (403, ProviderErrorCode.PERMISSION_DENIED),
        (404, ProviderErrorCode.NOT_FOUND),
        (418, ProviderErrorCode.PROVIDER_REJECTED),
    ),
)
def test_permanent_http_failures_do_not_retry(
    status: int,
    code: ProviderErrorCode,
) -> None:
    transport = _ScriptedTransport(iter((_response(status),)))
    executor = CurrentProviderRequestExecutor(transport, sleeper=lambda _: None)

    with pytest.raises(ProviderOperationError) as captured:
        executor.execute(_endpoint())

    assert captured.value.detail.code is code
    assert len(transport.requests) == 1


def test_retry_after_and_transport_failure_use_bounded_retry_policy() -> None:
    failure = ProviderTransportFailure(
        ProviderErrorCode.TRANSPORT_FAILURE,
        "safe transport failure",
    )
    transport = _ScriptedTransport(
        iter((failure, _response(429, retry_after_seconds=9), _response()))
    )
    delays: list[float] = []
    executor = CurrentProviderRequestExecutor(
        transport,
        retry_policy=ProviderRetryPolicy(
            maximum_attempts=3,
            base_delay_seconds=0.5,
            maximum_delay_seconds=2.0,
        ),
        sleeper=delays.append,
        clock=lambda: NOW,
    )

    assert executor.execute(_endpoint()).http_status == 200
    assert delays == [0.5, 2.0]


def test_exhausted_quota_blocks_calls_until_the_conservative_reset() -> None:
    exhausted = QuotaMetadata(
        status=QuotaStatus.EXHAUSTED,
        limit=100,
        remaining=0,
        resets_at=NOW + timedelta(minutes=5),
        retry_after_seconds=60,
    )
    transport = _ScriptedTransport(iter((_response(429, quota=exhausted), _response())))
    current_time = [NOW]
    executor = CurrentProviderRequestExecutor(
        transport,
        sleeper=lambda _: None,
        clock=lambda: current_time[0],
    )

    with pytest.raises(ProviderOperationError) as first:
        executor.execute(_endpoint())
    assert first.value.detail.code is ProviderErrorCode.QUOTA_EXHAUSTED

    with pytest.raises(ProviderOperationError) as blocked:
        executor.execute(_endpoint())
    assert blocked.value.detail.code is ProviderErrorCode.QUOTA_EXHAUSTED
    assert len(transport.requests) == 1

    current_time[0] = NOW + timedelta(minutes=5)
    assert executor.execute(_endpoint()).http_status == 200
    assert len(transport.requests) == 2


class _Headers(dict[str, str]):
    def get_content_charset(self) -> str | None:
        return "utf8"


class _ReadableResponse:
    status = 200
    code = 200
    headers = _Headers(
        {
            "Content-Type": "application/json; charset=utf8",
            "ETag": '"v1"',
            "Retry-After": "3",
        }
    )

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


def test_urllib_response_reader_preserves_bytes_and_enforces_size() -> None:
    raw = cast(HTTPResponse | HTTPError, _ReadableResponse(b'{"ok":true}\n'))
    parsed = UrllibProviderTransport._read_response(raw, 100)

    assert parsed.body == b'{"ok":true}\n'
    assert parsed.encoding == "utf-8"
    assert parsed.etag == '"v1"'
    assert parsed.retry_after_seconds == 3
    with pytest.raises(ProviderTransportFailure, match="byte limit"):
        UrllibProviderTransport._read_response(
            cast(HTTPResponse | HTTPError, _ReadableResponse(b"too-large")), 3
        )


def test_successful_transport_capture_preserves_exact_bytes_and_metadata() -> None:
    response = ProviderTransportResponse(
        body=b'{"answer":42}\n',
        http_status=200,
        media_type="application/json",
        encoding="utf-8",
        etag='"answer"',
        provider_request_id="request-1",
        quota=QuotaMetadata(
            status=QuotaStatus.AVAILABLE,
            limit=100,
            remaining=99,
        ),
    )

    capture = capture_successful_transport_response(
        _endpoint(),
        response,
        retrieved_at=NOW,
        compatibility=compatibility(),
        page=PageMetadata(returned_count=0, has_more=False),
        provider_generated_at=NOW - timedelta(seconds=1),
    )

    assert capture.response.body == response.body
    assert capture.provider_request_id == "request-1"
    assert capture.quota.remaining == 99
