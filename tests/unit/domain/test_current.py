"""Tests for provider-neutral current-season domain observations."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pl_platform.domain.current import (
    CURRENT_PROVIDER_FIELD_POLICIES,
    CompletedFixtureResult,
    CurrentSeasonFixture,
    CurrentSeasonScope,
    CurrentSeasonTeam,
    PredictorUsePolicy,
    ProviderCompetitionIdentifier,
    ProviderFixtureIdentifier,
    ProviderKickoff,
    ProviderSeasonIdentifier,
    ProviderTeamIdentifier,
    StandingRow,
)
from pl_platform.domain.fixtures import (
    FixtureScore,
    FixtureStatus,
    KickoffPrecision,
    MatchOutcome,
)

SOURCE = "test-provider"


def _competition(source: str = SOURCE) -> ProviderCompetitionIdentifier:
    return ProviderCompetitionIdentifier(source_id=source, external_id="PL")


def _season(source: str = SOURCE) -> ProviderSeasonIdentifier:
    return ProviderSeasonIdentifier(source_id=source, external_id="2026")


def _team(value: str, source: str = SOURCE) -> ProviderTeamIdentifier:
    return ProviderTeamIdentifier(source_id=source, external_id=value)


def _fixture(
    value: str = "fixture-1", source: str = SOURCE
) -> ProviderFixtureIdentifier:
    return ProviderFixtureIdentifier(source_id=source, external_id=value)


def _scope() -> CurrentSeasonScope:
    return CurrentSeasonScope(
        competition_id="eng-premier-league",
        season_id="2026-2027",
        provider_competition_id=_competition(),
        provider_season_id=_season(),
    )


def _kickoff() -> ProviderKickoff:
    return ProviderKickoff(
        kickoff_at=datetime(2026, 8, 15, 14, tzinfo=UTC),
        precision=KickoffPrecision.EXACT,
        source_timezone="Europe/London",
        source_local_date=date(2026, 8, 15),
    )


def test_provider_identifiers_are_explicit_and_not_canonical_ids() -> None:
    team = _team("team-1")

    assert team.external_id == "team-1"
    with pytest.raises(ValidationError):
        ProviderTeamIdentifier.model_validate(
            {"source_id": SOURCE, "external_id": " team-1"}
        )
    with pytest.raises(ValidationError):
        ProviderTeamIdentifier.model_validate(
            {"source_id": SOURCE, "external_id": "team-1", "canonical_id": "x"}
        )


def test_scope_rejects_cross_provider_or_invalid_season_identity() -> None:
    with pytest.raises(ValidationError, match="one source"):
        CurrentSeasonScope(
            competition_id="eng-premier-league",
            season_id="2026-2027",
            provider_competition_id=_competition(),
            provider_season_id=_season("other-provider"),
        )
    with pytest.raises(ValidationError, match="exactly one year"):
        CurrentSeasonScope.model_validate(
            {**_scope().model_dump(), "season_id": "2026-2028"}
        )


def test_exact_and_date_only_kickoffs_preserve_timezone_semantics() -> None:
    exact = _kickoff()
    date_only = ProviderKickoff(
        kickoff_at=datetime(2026, 8, 15, 11, tzinfo=UTC),
        precision=KickoffPrecision.DATE_ONLY,
        source_timezone="Europe/London",
        source_local_date=date(2026, 8, 15),
    )

    assert exact.kickoff_at.hour == 14
    assert date_only.kickoff_at.hour == 11

    with pytest.raises(ValidationError, match="noon anchor"):
        ProviderKickoff.model_validate(
            {
                **date_only.model_dump(),
                "kickoff_at": datetime(2026, 8, 15, 12, tzinfo=UTC),
            }
        )
    with pytest.raises(ValidationError, match="source-local date"):
        ProviderKickoff.model_validate(
            {**exact.model_dump(), "source_local_date": date(2026, 8, 16)}
        )
    with pytest.raises(ValidationError, match="IANA"):
        ProviderKickoff.model_validate(
            {**exact.model_dump(), "source_timezone": "Not/AZone"}
        )


def test_kickoff_requires_utc_not_merely_an_aware_offset() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ProviderKickoff.model_validate(
            {
                **_kickoff().model_dump(),
                "kickoff_at": datetime(
                    2026,
                    8,
                    15,
                    15,
                    tzinfo=timezone(timedelta(hours=1)),
                ),
            }
        )


def test_team_and_fixture_observations_remain_unresolved_and_score_free() -> None:
    team = CurrentSeasonTeam(provider_team_id=_team("home"), provider_name="Home")
    fixture = CurrentSeasonFixture(
        provider_fixture_id=_fixture(),
        home_provider_team_id=team.provider_team_id,
        away_provider_team_id=_team("away"),
        kickoff=_kickoff(),
        status=FixtureStatus.SCHEDULED,
    )

    assert fixture.status is FixtureStatus.SCHEDULED
    assert "canonical" not in fixture.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CurrentSeasonFixture.model_validate(
            {**fixture.model_dump(), "full_time_score": {"home": 1, "away": 0}}
        )
    with pytest.raises(ValidationError, match="teams must differ"):
        CurrentSeasonFixture.model_validate(
            {**fixture.model_dump(), "away_provider_team_id": team.provider_team_id}
        )
    with pytest.raises(ValidationError, match="one source"):
        CurrentSeasonFixture.model_validate(
            {
                **fixture.model_dump(),
                "away_provider_team_id": _team("away", "other"),
            }
        )


def test_completed_result_requires_finished_consistent_official_score() -> None:
    result = CompletedFixtureResult(
        provider_fixture_id=_fixture(),
        home_provider_team_id=_team("home"),
        away_provider_team_id=_team("away"),
        full_time_score=FixtureScore(home=2, away=1),
        outcome=MatchOutcome.HOME_WIN,
        completed_at=datetime(2026, 8, 15, 16, tzinfo=UTC),
    )

    assert result.status is FixtureStatus.FINISHED
    with pytest.raises(ValidationError, match="does not match"):
        CompletedFixtureResult.model_validate(
            {**result.model_dump(), "outcome": MatchOutcome.AWAY_WIN}
        )
    with pytest.raises(ValidationError):
        CompletedFixtureResult.model_validate(
            {**result.model_dump(), "status": FixtureStatus.ABANDONED}
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        CompletedFixtureResult.model_validate(
            {**result.model_dump(), "completed_at": datetime(2026, 8, 15, 16)}
        )


def test_standing_row_reconciles_results_goals_points_and_adjustment() -> None:
    row = StandingRow(
        provider_team_id=_team("home"),
        position=1,
        played=3,
        won=2,
        drawn=1,
        lost=0,
        goals_for=6,
        goals_against=2,
        goal_difference=4,
        points=5,
        points_adjustment=-2,
    )

    assert row.points == 5
    for field, value, message in (
        ("played", 4, "played count"),
        ("goal_difference", 3, "goal difference"),
        ("points", 6, "points do not reconcile"),
    ):
        with pytest.raises(ValidationError, match=message):
            StandingRow.model_validate({**row.model_dump(), field: value})


def test_field_policy_is_canonical_and_keeps_odds_prohibited() -> None:
    paths = tuple(item.field_path for item in CURRENT_PROVIDER_FIELD_POLICIES)
    odds = next(
        item
        for item in CURRENT_PROVIDER_FIELD_POLICIES
        if item.field_path == "wagering.betting_odds"
    )

    assert paths == tuple(sorted(set(paths)))
    assert odds.predictor_use is PredictorUsePolicy.PROHIBITED
    assert not any(
        "player" in item.field_path for item in CURRENT_PROVIDER_FIELD_POLICIES
    )
