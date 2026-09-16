"""Safe current-data job CLI tests."""

import io
import json
import subprocess
import sys
from dataclasses import dataclass, field

import pytest

from pl_platform.automation.cli import (
    CurrentDataJobRequest,
    CurrentDataJobSummary,
    main,
)


@dataclass
class _Runner:
    requests: list[CurrentDataJobRequest] = field(default_factory=list)

    def run(self, request: CurrentDataJobRequest) -> CurrentDataJobSummary:
        self.requests.append(request)
        return CurrentDataJobSummary(
            command=request.command,
            target=request.target,
            season_id=request.season_id,
            evaluated_at=request.at.isoformat(),
            status="completed",
            item_count=3,
            page_count=1,
            next_poll_at=None,
        )


@pytest.mark.parametrize("command", ("poll-fixtures", "reconcile-final-matches"))
def test_cli_dispatches_explicit_nonproduction_jobs_as_canonical_json(
    command: str,
) -> None:
    runner = _Runner()
    output = io.StringIO()

    exit_code = main(
        [
            command,
            "--target",
            "test",
            "--season-id",
            "2026-2027",
            "--at",
            "2026-09-16T10:00:00Z",
        ],
        runner=runner,
        stdout=output,
    )

    assert exit_code == 0
    assert runner.requests[0].target.value == "test"
    assert json.loads(output.getvalue())["status"] == "completed"
    assert output.getvalue() == "".join(sorted((output.getvalue(),)))


def test_cli_fails_closed_without_runtime_dependencies() -> None:
    errors = io.StringIO()

    exit_code = main(
        [
            "poll-fixtures",
            "--target",
            "development",
            "--season-id",
            "2026-2027",
            "--at",
            "2026-09-16T10:00:00+00:00",
        ],
        stderr=errors,
    )

    assert exit_code == 2
    assert json.loads(errors.getvalue()) == {
        "error": {
            "code": "job_unavailable",
            "message": (
                "current-data provider and database dependencies are not configured"
            ),
        }
    }


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "--target",
            "production",
            "--season-id",
            "2026-2027",
            "--at",
            "2026-09-16T10:00:00Z",
        ),
        (
            "--target",
            "test",
            "--season-id",
            "2027-2026",
            "--at",
            "2026-09-16T10:00:00Z",
        ),
        ("--target", "test", "--season-id", "2026-2027", "--at", "2026-09-16T10:00:00"),
        ("--target", "test", "--season-id", "2026-2027", "--at", "not-a-date"),
    ),
)
def test_cli_rejects_production_and_nondeterministic_inputs(
    arguments: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit):
        main(["poll-fixtures", *arguments])


def test_cli_import_has_no_database_or_provider_side_effects() -> None:
    script = """
import pl_platform.persistence.database as database
def fail(*args, **kwargs):
    raise AssertionError("CLI import performed runtime work")
database.create_database_engine = fail
import pl_platform.automation.cli
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
