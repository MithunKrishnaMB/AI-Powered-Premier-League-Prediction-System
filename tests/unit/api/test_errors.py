"""Tests for request IDs and uniform API error envelopes."""

from uuid import UUID

import pytest
from fastapi import HTTPException, Query
from fastapi.testclient import TestClient

from pl_platform.api.application import create_app
from pl_platform.api.errors import ApiError, ErrorDetail, get_request_id
from pl_platform.api.health import ReadinessService
from pl_platform.core.config import Settings

REQUEST_ID = "stable-request-123"


def _client() -> TestClient:
    app = create_app(
        settings=Settings(),
        readiness=ReadinessService(probes=()),
    )

    @app.get("/_test/validation")
    def validation(value: int = Query(ge=1)) -> dict[str, int]:
        return {"value": value}

    @app.get("/_test/api-error")
    def api_error() -> None:
        raise ApiError(
            status_code=409,
            code="synthetic_conflict",
            message="Synthetic conflict.",
            details=(
                ErrorDetail(
                    location=("resource",),
                    code="conflict",
                    message="Resource conflicts.",
                ),
            ),
        )

    @app.get("/_test/http-error")
    def http_error() -> None:
        raise HTTPException(status_code=418, detail="must not be exposed")

    @app.get("/_test/unhandled")
    def unhandled() -> None:
        raise RuntimeError("must not be exposed")

    @app.get("/_test/request-id")
    def request_id() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_is_echoed_and_available_in_request_context() -> None:
    with _client() as client:
        response = client.get(
            "/_test/request-id",
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert response.json() == {"request_id": REQUEST_ID}
    assert get_request_id() is None


def test_missing_request_id_generates_a_canonical_uuid() -> None:
    with _client() as client:
        response = client.get("/health/live")

    generated = response.headers["X-Request-ID"]
    assert str(UUID(generated)) == generated
    assert response.json() == {"schema_version": 1, "status": "alive"}


def test_invalid_or_duplicate_request_id_returns_a_sanitized_400() -> None:
    with _client() as client:
        invalid = client.get("/health/live", headers={"X-Request-ID": "bad id"})
        duplicate = client.get(
            "/health/live",
            headers=[("X-Request-ID", "one"), ("X-Request-ID", "two")],
        )

    for response in (invalid, duplicate):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request_id"
        assert (
            response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        )


def test_routing_and_validation_errors_use_the_uniform_envelope() -> None:
    with _client() as client:
        missing = client.get("/missing", headers={"X-Request-ID": REQUEST_ID})
        method = client.post(
            "/health/live",
            headers={"X-Request-ID": REQUEST_ID},
        )
        validation = client.get(
            "/_test/validation?value=0",
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert method.status_code == 405
    assert method.json()["error"]["code"] == "method_not_allowed"
    assert validation.status_code == 422
    assert validation.json()["error"] == {
        "code": "request_validation_failed",
        "message": "Request validation failed.",
        "request_id": REQUEST_ID,
        "details": [
            {
                "location": ["query", "value"],
                "code": "greater_than_equal",
                "message": "Input should be greater than or equal to 1",
            }
        ],
    }


def test_explicit_http_and_api_errors_do_not_expose_internal_details() -> None:
    with _client() as client:
        api_error = client.get(
            "/_test/api-error",
            headers={"X-Request-ID": REQUEST_ID},
        )
        http_error = client.get(
            "/_test/http-error",
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert api_error.status_code == 409
    assert api_error.json()["error"]["code"] == "synthetic_conflict"
    assert api_error.json()["error"]["details"][0]["code"] == "conflict"
    assert http_error.status_code == 418
    assert http_error.json()["error"]["code"] == "http_error"
    assert "must not be exposed" not in http_error.text


def test_unhandled_exception_is_a_generic_500_with_request_id() -> None:
    with _client() as client:
        response = client.get(
            "/_test/unhandled",
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert response.status_code == 500
    assert response.json() == {
        "schema_version": 1,
        "error": {
            "code": "internal_server_error",
            "message": "An internal server error occurred.",
            "request_id": REQUEST_ID,
            "details": [],
        },
    }
    assert "must not be exposed" not in response.text


def test_api_error_rejects_invalid_status_and_code() -> None:
    with pytest.raises(ValueError, match="status code"):
        ApiError(status_code=200, code="not_an_error", message="Invalid.")
    with pytest.raises(ValueError, match="identifier syntax"):
        ApiError(status_code=400, code="bad code", message="Invalid.")
