"""Factory-scoped CORS, security-header and rate-limit controls."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic
from typing import Final

from fastapi import Request, Response, status

from pl_platform.api.errors import error_response
from pl_platform.core.config import Settings

_ALLOWED_METHODS: Final = ("GET", "OPTIONS")
_ALLOWED_HEADERS: Final = ("Accept", "Content-Type", "X-Request-ID")
_EXPOSED_HEADERS: Final = (
    "X-Request-ID",
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "Retry-After",
)
_STRICT_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
_DOCS_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """One deterministic sliding-window decision and response metadata."""

    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int
    retry_after_seconds: int | None


class SlidingWindowRateLimiter:
    """Bounded, process-local rate limiter keyed only by the direct peer."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        max_clients: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def evaluate(self, client_key: str) -> RateLimitDecision:
        """Consume one request or return a stable retry interval."""

        now = self._clock()
        threshold = now - self._window_seconds
        with self._lock:
            timestamps = self._clients.get(client_key)
            if timestamps is None:
                if len(self._clients) >= self._max_clients:
                    self._clients.popitem(last=False)
                timestamps = deque()
                self._clients[client_key] = timestamps
            else:
                self._clients.move_to_end(client_key)
            while timestamps and timestamps[0] <= threshold:
                timestamps.popleft()

            if len(timestamps) >= self._limit:
                retry_after = max(
                    1,
                    ceil(self._window_seconds - (now - timestamps[0])),
                )
                return RateLimitDecision(
                    allowed=False,
                    limit=self._limit,
                    remaining=0,
                    reset_after_seconds=retry_after,
                    retry_after_seconds=retry_after,
                )

            timestamps.append(now)
            reset_after = max(
                1,
                ceil(self._window_seconds - (now - timestamps[0])),
            )
            return RateLimitDecision(
                allowed=True,
                limit=self._limit,
                remaining=self._limit - len(timestamps),
                reset_after_seconds=reset_after,
                retry_after_seconds=None,
            )


def _append_vary(response: Response, *values: str) -> None:
    existing = {
        item.strip()
        for item in response.headers.get("Vary", "").split(",")
        if item.strip()
    }
    existing.update(values)
    response.headers["Vary"] = ", ".join(sorted(existing))


@dataclass(frozen=True, slots=True)
class HttpTransportControls:
    """Apply the complete HTTP control policy around one request."""

    settings: Settings
    rate_limiter: SlidingWindowRateLimiter

    def before_request(self, request: Request, request_id: str) -> Response | None:
        """Reject invalid CORS or rate state before route execution."""

        origins = request.headers.getlist("Origin")
        if len(origins) > 1:
            return error_response(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_cors_origin",
                message="Origin is invalid.",
            )
        origin = origins[0] if origins else None
        if origin is not None and origin not in self.settings.cors_allowed_origins:
            return error_response(
                request_id=request_id,
                status_code=status.HTTP_403_FORBIDDEN,
                code="cors_origin_denied",
                message="Origin is not allowed.",
            )
        if request.method == "OPTIONS":
            return self._preflight_response(request, request_id, origin)
        if not self.settings.rate_limit_enabled or request.url.path == "/health/live":
            return None

        client_key = request.client.host if request.client is not None else "unknown"
        decision = self.rate_limiter.evaluate(client_key)
        request.state.rate_limit_decision = decision
        if decision.allowed:
            return None
        return error_response(
            request_id=request_id,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limit_exceeded",
            message="Rate limit exceeded.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    def _preflight_response(
        self,
        request: Request,
        request_id: str,
        origin: str | None,
    ) -> Response:
        if origin is None:
            return error_response(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="cors_preflight_rejected",
                message="CORS preflight is invalid.",
            )
        requested_method = request.headers.get("Access-Control-Request-Method")
        requested_headers = {
            item.strip().casefold()
            for item in request.headers.get(
                "Access-Control-Request-Headers",
                "",
            ).split(",")
            if item.strip()
        }
        allowed_headers = {header.casefold() for header in _ALLOWED_HEADERS}
        if requested_method != "GET" or not requested_headers <= allowed_headers:
            return error_response(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="cors_preflight_rejected",
                message="CORS preflight is invalid.",
            )
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.headers["Access-Control-Allow-Methods"] = ", ".join(_ALLOWED_METHODS)
        response.headers["Access-Control-Allow-Headers"] = ", ".join(_ALLOWED_HEADERS)
        response.headers["Access-Control-Max-Age"] = str(
            self.settings.cors_max_age_seconds
        )
        _append_vary(
            response,
            "Origin",
            "Access-Control-Request-Method",
            "Access-Control-Request-Headers",
        )
        return response

    def after_response(self, request: Request, response: Response) -> None:
        """Attach stable security, CORS and rate-limit response metadata."""

        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Content-Security-Policy"] = (
            _DOCS_CONTENT_SECURITY_POLICY
            if request.url.path == "/docs"
            else _STRICT_CONTENT_SECURITY_POLICY
        )
        if self.settings.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        origin = request.headers.get("Origin")
        if origin is not None and origin in self.settings.cors_allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = ", ".join(
                _EXPOSED_HEADERS
            )
            if self.settings.cors_allow_credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"
            _append_vary(response, "Origin")

        decision = getattr(request.state, "rate_limit_decision", None)
        if isinstance(decision, RateLimitDecision):
            response.headers["RateLimit-Limit"] = str(decision.limit)
            response.headers["RateLimit-Remaining"] = str(decision.remaining)
            response.headers["RateLimit-Reset"] = str(decision.reset_after_seconds)


def default_http_transport_controls(settings: Settings) -> HttpTransportControls:
    """Construct process-local controls without performing external I/O."""

    return HttpTransportControls(
        settings=settings,
        rate_limiter=SlidingWindowRateLimiter(
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
            max_clients=settings.rate_limit_max_clients,
        ),
    )
