"""Fail-closed CLI entry points for current-data jobs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, TextIO


class CurrentDataJobCommand(StrEnum):
    POLL_FIXTURES = "poll-fixtures"
    RECONCILE_FINAL_MATCHES = "reconcile-final-matches"


class CurrentDataJobTarget(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class CurrentDataJobRequest:
    command: CurrentDataJobCommand
    target: CurrentDataJobTarget
    season_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class CurrentDataJobSummary:
    command: CurrentDataJobCommand
    target: CurrentDataJobTarget
    season_id: str
    evaluated_at: str
    status: str
    item_count: int
    page_count: int
    next_poll_at: str | None = None


class CurrentDataJobRunner(Protocol):
    def run(self, request: CurrentDataJobRequest) -> CurrentDataJobSummary: ...


class CurrentDataJobUnavailableError(RuntimeError):
    """Raised when intentionally absent runtime dependencies prevent a job."""


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise argparse.ArgumentTypeError("must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _season_id(value: str) -> str:
    parts = value.split("-")
    if (
        len(parts) != 2
        or any(len(part) != 4 or not part.isdigit() for part in parts)
        or int(parts[1]) != int(parts[0]) + 1
    ):
        raise argparse.ArgumentTypeError("must use consecutive YYYY-YYYY seasons")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plp-current-data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in CurrentDataJobCommand:
        subparser = subparsers.add_parser(command.value)
        subparser.add_argument(
            "--target",
            choices=tuple(item.value for item in CurrentDataJobTarget),
            required=True,
        )
        subparser.add_argument("--season-id", type=_season_id, required=True)
        subparser.add_argument("--at", type=_utc_datetime, required=True)
    return parser


class _UnavailableRunner:
    def run(self, request: CurrentDataJobRequest) -> CurrentDataJobSummary:
        del request
        raise CurrentDataJobUnavailableError(
            "current-data provider and database dependencies are not configured"
        )


def main(
    argv: list[str] | None = None,
    *,
    runner: CurrentDataJobRunner | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    namespace = _parser().parse_args(argv)
    request = CurrentDataJobRequest(
        command=CurrentDataJobCommand(namespace.command),
        target=CurrentDataJobTarget(namespace.target),
        season_id=str(namespace.season_id),
        at=namespace.at,
    )
    try:
        summary = (runner or _UnavailableRunner()).run(request)
    except CurrentDataJobUnavailableError as exc:
        errors.write(
            json.dumps(
                {
                    "error": {
                        "code": "job_unavailable",
                        "message": str(exc),
                    }
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        return 2
    output.write(
        json.dumps(asdict(summary), separators=(",", ":"), sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
