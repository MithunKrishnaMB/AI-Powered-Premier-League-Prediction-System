"""Request IDs and stable, sanitized API error envelopes."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar, Token
from typing import Final, Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

REQUEST_ID_HEADER: Final = "X-Request-ID"
_REQUEST_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_current_request_id: ContextVar[str | None] = ContextVar(
    "pl_platform_request_id",
    default=None,
)
type RequestHandler = Callable[[Request], Awaitable[Response]]
type ErrorLocationPart = str | int


class ErrorModel(BaseModel):
    """Strict immutable base for public error contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorDetail(ErrorModel):
    """One safe validation or domain-error detail."""

    location: tuple[ErrorLocationPart, ...]
    code: str
    message: str


class ErrorBody(ErrorModel):
    """Stable public error payload."""

    code: str
    message: str
    request_id: str
    details: tuple[ErrorDetail, ...] = ()


class ErrorEnvelope(ErrorModel):
    """Uniform wrapper for every API error response."""

    schema_version: Literal[1] = 1
    error: ErrorBody


class ApiError(Exception):
    """Intentional future endpoint failure with a stable public contract."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ErrorDetail] = (),
    ) -> None:
        if not 400 <= status_code <= 599:
            msg = "API error status code must be between 400 and 599"
            raise ValueError(msg)
        if _REQUEST_ID_PATTERN.fullmatch(code) is None:
            msg = "API error code must use the stable identifier syntax"
            raise ValueError(msg)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = tuple(details)
        super().__init__(code)


def get_request_id() -> str | None:
    """Return the current request ID for internal logging or delegation."""

    return _current_request_id.get()


def _request_id_from(request: Request) -> tuple[str, bool]:
    supplied = request.headers.getlist(REQUEST_ID_HEADER)
    if not supplied:
        return str(uuid4()), True
    if len(supplied) != 1 or _REQUEST_ID_PATTERN.fullmatch(supplied[0]) is None:
        return str(uuid4()), False
    return supplied[0], True


def _known_request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else str(uuid4())


def error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: Sequence[ErrorDetail] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Serialize one deterministic envelope without unsafe exception data."""

    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=tuple(details),
        )
    )
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=response_headers,
    )


def _http_error_contract(status_code: int) -> tuple[str, str]:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found", "Resource not found."
    if status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        return "method_not_allowed", "Method not allowed."
    return "http_error", "The request could not be completed."


def _validation_details(error: RequestValidationError) -> tuple[ErrorDetail, ...]:
    details: list[ErrorDetail] = []
    for item in error.errors():
        raw_location = item.get("loc", ())
        location = tuple(
            part if isinstance(part, (str, int)) else str(part) for part in raw_location
        )
        details.append(
            ErrorDetail(
                location=location,
                code=str(item.get("type", "validation_error")),
                message=str(item.get("msg", "Invalid value.")),
            )
        )
    return tuple(details)


def install_error_boundary(app: FastAPI) -> None:
    """Install request-ID middleware and uniform exception handlers."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            request_id=_known_request_id(request),
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request_id=_known_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="request_validation_failed",
            message="Request validation failed.",
            details=_validation_details(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code, message = _http_error_contract(exc.status_code)
        return error_response(
            request_id=_known_request_id(request),
            status_code=exc.status_code,
            code=code,
            message=message,
            headers=dict(exc.headers or {}),
        )

    @app.middleware("http")
    async def request_id_boundary(
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        request_id, valid = _request_id_from(request)
        request.state.request_id = request_id
        token: Token[str | None] = _current_request_id.set(request_id)
        try:
            if not valid:
                response: Response = error_response(
                    request_id=request_id,
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="invalid_request_id",
                    message="X-Request-ID is invalid.",
                )
            else:
                try:
                    response = await call_next(request)
                except Exception:
                    response = error_response(
                        request_id=request_id,
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        code="internal_server_error",
                        message="An internal server error occurred.",
                    )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _current_request_id.reset(token)
