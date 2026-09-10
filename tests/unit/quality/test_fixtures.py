"""Tests for cross-fixture Premier League quality rules."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatistics,
    FixtureStatus,
    MatchOutcome,
    SourceFixtureReference,
    TeamMatchStatistics,
)
from pl_platform.domain.seasons import PremierLeagueSeason, load_season_registry
from pl_platform.domain.teams import load_team_registry
from pl_platform.quality.fixtures import (
    DataQualityError,
    QualitySeverity,
    validate_premier_league_fixtures,
)


def _season() -> PremierLeagueSeason:
    teams = load_team_registry(Path("data/reference/teams.json"))
    return load_season_registry(
        Path("data/reference/seasons.json"),
        teams,
    ).get("2025-2026")


def complete_fixtures() -> tuple[Fixture, ...]:
    season = _season()
    fixtures: list[Fixture] = []
    for home_team_id in season.team_ids:
        for away_team_id in season.team_ids:
            if home_team_id == away_team_id:
                continue
            identity = f"{season.id}:{home_team_id}:{away_team_id}"
            fixtures.append(
                Fixture(
                    id=uuid5(NAMESPACE_URL, identity),
                    competition_id=season.competition_id,
                    season_id=season.id,
                    kickoff_at=datetime(2026, 1, 1, 15, tzinfo=UTC),
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    status=FixtureStatus.FINISHED,
                    full_time_score=FixtureScore(home=0, away=0),
                    outcome=MatchOutcome.DRAW,
                    statistics=FixtureStatistics(
                        home=TeamMatchStatistics(),
                        away=TeamMatchStatistics(),
                    ),
                    source_references=(
                        SourceFixtureReference(
                            source_id="test",
                            external_id=identity,
                        ),
                    ),
                )
            )
    return tuple(fixtures)


def _codes(fixtures: tuple[Fixture, ...]) -> set[str]:
    return {
        issue.code
        for issue in validate_premier_league_fixtures(fixtures, _season()).issues
    }


def test_accepts_complete_double_round_robin() -> None:
    report = validate_premier_league_fixtures(complete_fixtures(), _season())

    assert report.checked_fixtures == 380
    assert report.is_valid
    assert report.errors == ()
    assert report.warnings == ()


def test_detects_duplicate_and_missing_pairings() -> None:
    fixtures = complete_fixtures()
    changed = (*fixtures[:-1], fixtures[0])

    codes = _codes(changed)

    assert "duplicate_fixture_id" in codes
    assert "duplicate_home_away_pair" in codes
    assert "home_fixture_count" in codes
    assert "away_fixture_count" in codes


def test_detects_incomplete_schedule() -> None:
    codes = _codes(complete_fixtures()[:-1])

    assert "fixture_count" in codes
    assert "home_fixture_count" in codes
    assert "away_fixture_count" in codes


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"competition_id": "other"}, "competition_mismatch"),
        ({"season_id": "2024-2025"}, "season_mismatch"),
        (
            {"home_team_id": UUID("00000000-0000-0000-0000-000000000000")},
            "unknown_season_team",
        ),
        (
            {"kickoff_at": datetime(2024, 1, 1, 15, tzinfo=UTC)},
            "kickoff_outside_season",
        ),
        ({"status": FixtureStatus.POSTPONED}, "unfinished_completed_season"),
    ],
)
def test_detects_cross_record_inconsistency(
    changes: dict[str, object],
    expected_code: str,
) -> None:
    fixtures = list(complete_fixtures())
    fixtures[0] = fixtures[0].model_copy(update=changes)

    assert expected_code in _codes(tuple(fixtures))


def test_missing_optional_statistics_is_warning_only() -> None:
    fixtures = list(complete_fixtures())
    fixtures[0] = fixtures[0].model_copy(update={"statistics": None})

    report = validate_premier_league_fixtures(tuple(fixtures), _season())

    assert report.is_valid
    assert len(report.warnings) == 1
    assert report.warnings[0].severity == QualitySeverity.WARNING


def test_data_quality_error_exposes_report() -> None:
    report = validate_premier_league_fixtures(complete_fixtures()[:-1], _season())

    error = DataQualityError(report)

    assert error.report is report
    assert "fixture_count" in str(error)
