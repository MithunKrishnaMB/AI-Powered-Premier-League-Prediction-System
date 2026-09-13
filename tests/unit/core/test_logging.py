"""Tests for structured logging and secret redaction."""

import json
import logging
import sys
from io import StringIO
from typing import cast

import pytest

from pl_platform.core.logging import REDACTED, JsonFormatter, configure_logging


def _payload(line: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads(line))


def test_formatter_emits_json_context_and_redacts_secrets() -> None:
    record = logging.LogRecord(
        name="pl_platform.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="processed %s",
        args=("fixture",),
        exc_info=None,
    )
    record.__dict__["fixture_id"] = 42
    record.__dict__["api_key"] = "do-not-log"
    record.__dict__["database_url"] = "postgresql+psycopg://user:secret@host/db"
    record.__dict__["dsn"] = "host=localhost password=secret"
    record.__dict__["details"] = {"token": "hidden", "rows": [1, 2]}

    payload = _payload(JsonFormatter().format(record))
    context = cast(dict[str, object], payload["context"])
    details = cast(dict[str, object], context["details"])

    assert payload["message"] == "processed fixture"
    assert context["fixture_id"] == 42
    assert context["api_key"] == REDACTED
    assert context["database_url"] == REDACTED
    assert context["dsn"] == REDACTED
    assert details["token"] == REDACTED
    assert details["rows"] == [1, 2]


def test_formatter_includes_exception() -> None:
    try:
        raise RuntimeError("provider failed")
    except RuntimeError:
        record = logging.LogRecord(
            name="pl_platform.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="sync failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = _payload(JsonFormatter().format(record))

    assert "RuntimeError: provider failed" in cast(str, payload["exception"])


def test_configure_logging_writes_json() -> None:
    stream = StringIO()
    root_logger = logging.getLogger()
    previous_handlers = root_logger.handlers.copy()
    previous_level = root_logger.level

    try:
        configure_logging("warning", stream)
        logging.getLogger("pl_platform.test").warning(
            "fixture synchronized",
            extra={"fixture_id": 42},
        )
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    payload = _payload(stream.getvalue())

    assert payload["level"] == "WARNING"
    assert payload["message"] == "fixture synchronized"


def test_configure_logging_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="Unsupported log level"):
        configure_logging("verbose")
