"""Tests for CORS, security headers and bounded process-local rate controls."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.api.controls import (
    HttpTransportControls,
    SlidingWindowRateLimiter,
)
from pl_platform.core.config import Settings

REQUEST_ID = "transport-control-test"
ALLOWED_ORIGIN = "https://app.example"


@dataclass(slots=True)
class MutableClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value


def _controlled_client(
    *,
    limit: int = 2,
    clock: MutableClock | None = None,
    credentials: bool = True,
) -> TestClient:
    settings = Settings(
        cors_allowed_origins=(ALLOWED_ORIGIN,),
        cors_allow_credentials=credentials,
        rate_limit_requests=limit,
        rate_limit_window_seconds=60,
        rate_limit_max_clients=2,
    )
    limiter = SlidingWindowRateLimiter(
        limit=limit,
        window_seconds=60,
        max_clients=2,
        clock=clock or MutableClock(),
    )
    controls = HttpTransportControls(settings=settings, rate_limiter=limiter)
    return TestClient(create_app(settings=settings, controls=controls))


def test_allowed_cors_and_preflight_receive_security_headers() -> None:
    with _controlled_client() as client:
        actual = client.get(
            "/health/live",
            headers={"Origin": ALLOWED_ORIGIN, "X-Request-ID": REQUEST_ID},
        )
        preflight = client.options(
            "/api/v1/teams",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID, Content-Type",
                "X-Request-ID": REQUEST_ID,
            },
        )

    assert actual.status_code == 200
    assert preflight.status_code == 204
    for response in (actual, preflight):
        assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Request-ID"] == REQUEST_ID
        assert "Origin" in response.headers["Vary"]
    assert preflight.headers["Access-Control-Allow-Methods"] == "GET, OPTIONS"
    assert preflight.headers["Access-Control-Max-Age"] == "600"


def test_cors_denials_use_sanitized_error_envelopes() -> None:
    with _controlled_client() as client:
        denied = client.get(
            "/health/live",
            headers={"Origin": "https://denied.example", "X-Request-ID": REQUEST_ID},
        )
        missing_origin = client.options(
            "/api/v1/teams",
            headers={
                "Access-Control-Request-Method": "GET",
                "X-Request-ID": REQUEST_ID,
            },
        )
        bad_method = client.options(
            "/api/v1/teams",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "X-Request-ID": REQUEST_ID,
            },
        )
        bad_headers = client.options(
            "/api/v1/teams",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
                "X-Request-ID": REQUEST_ID,
            },
        )
        duplicate = client.get(
            "/health/live",
            headers=[
                ("Origin", ALLOWED_ORIGIN),
                ("Origin", ALLOWED_ORIGIN),
                ("X-Request-ID", REQUEST_ID),
            ],
        )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "cors_origin_denied"
    for response in (missing_origin, bad_method, bad_headers):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "cors_preflight_rejected"
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "invalid_cors_origin"
    assert "denied.example" not in denied.text


def test_rate_limit_is_stable_expires_and_does_not_limit_liveness() -> None:
    clock = MutableClock()
    with _controlled_client(clock=clock) as client:
        for _ in range(5):
            assert client.get("/health/live").status_code == 200
        first = client.get("/openapi.json", headers={"X-Request-ID": REQUEST_ID})
        second = client.get("/openapi.json", headers={"X-Request-ID": REQUEST_ID})
        limited = client.get("/openapi.json", headers={"X-Request-ID": REQUEST_ID})
        clock.value += 61
        recovered = client.get("/openapi.json", headers={"X-Request-ID": REQUEST_ID})

    assert first.headers["RateLimit-Remaining"] == "1"
    assert second.headers["RateLimit-Remaining"] == "0"
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["RateLimit-Remaining"] == "0"
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert recovered.status_code == 200
    assert recovered.headers["RateLimit-Remaining"] == "1"


def test_security_policy_varies_for_docs_and_production_hsts() -> None:
    settings = Settings(environment="production", rate_limit_enabled=False)
    with TestClient(create_app(settings=settings)) as client:
        docs = client.get("/docs", headers={"X-Request-ID": REQUEST_ID})
        live = client.get("/health/live", headers={"X-Request-ID": REQUEST_ID})
        invalid_id = client.get("/health/live", headers={"X-Request-ID": "invalid id"})

    assert docs.status_code == live.status_code == 200
    assert "cdn.jsdelivr.net" in docs.headers["Content-Security-Policy"]
    assert live.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert live.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    assert invalid_id.status_code == 400
    assert invalid_id.headers["X-Content-Type-Options"] == "nosniff"


def test_rate_limiter_bounds_client_state_and_handles_unknown_clients() -> None:
    clock = MutableClock()
    limiter = SlidingWindowRateLimiter(
        limit=1,
        window_seconds=10,
        max_clients=2,
        clock=clock,
    )

    assert limiter.evaluate("first").allowed
    assert limiter.evaluate("second").allowed
    assert limiter.evaluate("third").allowed
    assert limiter.evaluate("third").allowed is False
    clock.value += 11
    decision = limiter.evaluate("third")

    assert decision.allowed
    assert decision.remaining == 0
