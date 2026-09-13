"""Structured application logging with defensive secret redaction."""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TextIO

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "database_url",
    "dsn",
    "password",
    "secret",
    "token",
)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def _redact(value: object, key: str | None = None) -> object:
    if key is not None and any(
        sensitive_part in key.casefold() for sensitive_part in _SENSITIVE_KEY_PARTS
    ):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = {
            key: _redact(value, key)
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure the root logger for structured application output."""

    normalized_level = level.upper()
    level_number = logging.getLevelNamesMapping().get(normalized_level)
    if not isinstance(level_number, int):
        msg = f"Unsupported log level: {level}"
        raise ValueError(msg)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level_number)
