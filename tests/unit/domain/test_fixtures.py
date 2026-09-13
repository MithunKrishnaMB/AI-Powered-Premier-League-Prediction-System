"""Tests for canonical fixture invariants."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatus,
    KickoffPrecision,
    MatchOutcome,
    SourceFixtureReference,
)

FIXTURE_ID = UUID("e5358903-3112-54e5-9260-590bd63824ac")
HOME_TEAM_ID = UUID("6f4ce9e1-6d36-5198-af34-7aca2aac351e")
AWAY_TEAM_ID = UUID("cfde9ca5-a6d2-5ec5-acaf-3a739dcd9c5b")


def _fixture_payload() -> dict[str, object]:
    return {
        "id": FIXTURE_ID,
        "competition_id": "eng-premier-league",
        "season_id": "2025-2026",
        "kickoff_at": datetime(2025, 8, 15, 19, tzinfo=UTC),
        "home_team_id": HOME_TEAM_ID,
        "away_team_id": AWAY_TEAM_ID,
        "status": FixtureStatus.FINISHED,
        "full_time_score": FixtureScore(home=2, away=1),
        "half_time_score": FixtureScore(home=1, away=0),
        "outcome": MatchOutcome.HOME_WIN,
        "source_references": (
            SourceFixtureReference(source_id="source", external_id="row:2"),
        ),
    }


@pytest.mark.parametrize(
    ("score", "outcome"),
    [
        (FixtureScore(home=2, away=1), MatchOutcome.HOME_WIN),
        (FixtureScore(home=1, away=1), MatchOutcome.DRAW),
        (FixtureScore(home=0, away=1), MatchOutcome.AWAY_WIN),
    ],
)
def test_score_derives_outcome(score: FixtureScore, outcome: MatchOutcome) -> None:
    assert score.outcome == outcome


def test_accepts_consistent_finished_fixture() -> None:
    fixture = Fixture.model_validate(_fixture_payload())

    assert fixture.status == FixtureStatus.FINISHED
    assert fixture.kickoff_precision == KickoffPrecision.EXACT


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "kickoff_at",
            datetime(2025, 8, 15, 20, tzinfo=timezone(timedelta(hours=1))),
            "timezone-aware UTC",
        ),
        ("away_team_id", HOME_TEAM_ID, "teams must differ"),
        ("outcome", MatchOutcome.AWAY_WIN, "does not match"),
        ("half_time_score", FixtureScore(home=3, away=0), "cannot exceed"),
    ],
)
def test_rejects_inconsistent_finished_fixture(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _fixture_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        Fixture.model_validate(payload)


def test_rejects_finished_fixture_without_score() -> None:
    payload = _fixture_payload()
    payload["full_time_score"] = None

    with pytest.raises(ValidationError, match="require a full-time score"):
        Fixture.model_validate(payload)


def test_rejects_score_on_scheduled_fixture() -> None:
    payload = _fixture_payload()
    payload["status"] = FixtureStatus.SCHEDULED

    with pytest.raises(ValidationError, match="cannot contain"):
        Fixture.model_validate(payload)


def test_accepts_postponed_fixture_without_score() -> None:
    payload = _fixture_payload()
    payload.update(
        {
            "status": FixtureStatus.POSTPONED,
            "full_time_score": None,
            "half_time_score": None,
            "outcome": None,
        }
    )

    fixture = Fixture.model_validate(payload)

    assert fixture.status == FixtureStatus.POSTPONED


@pytest.mark.parametrize(
    "status",
    [FixtureStatus.IN_PROGRESS, FixtureStatus.ABANDONED],
)
def test_non_finished_current_states_reject_official_scores(
    status: FixtureStatus,
) -> None:
    payload = _fixture_payload()
    payload["status"] = status

    with pytest.raises(ValidationError, match="cannot contain"):
        Fixture.model_validate(payload)


def test_accepts_abandoned_fixture_without_score() -> None:
    payload = _fixture_payload()
    payload.update(
        {
            "status": FixtureStatus.ABANDONED,
            "full_time_score": None,
            "half_time_score": None,
            "outcome": None,
        }
    )

    fixture = Fixture.model_validate(payload)

    assert fixture.status is FixtureStatus.ABANDONED
