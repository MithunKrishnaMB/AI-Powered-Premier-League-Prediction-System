"""Transform provider rows into canonical football-domain records."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatistics,
    FixtureStatus,
    KickoffPrecision,
    MatchOutcome,
    SourceFixtureReference,
    TeamMatchStatistics,
    canonical_fixture_id,
)
from pl_platform.domain.teams import TeamRegistry
from pl_platform.ingestion.football_data import (
    FootballDataMatch,
    FootballDataResult,
)

PREMIER_LEAGUE_COMPETITION_ID = "eng-premier-league"
_FOOTBALL_DATA_TIMEZONE = ZoneInfo("Europe/London")
_DATE_ONLY_ANCHOR = time(12, 0)


class CanonicalizationError(ValueError):
    """A valid source row cannot be represented by the canonical contract."""


def _outcome(result: FootballDataResult) -> MatchOutcome:
    return {
        FootballDataResult.HOME: MatchOutcome.HOME_WIN,
        FootballDataResult.DRAW: MatchOutcome.DRAW,
        FootballDataResult.AWAY: MatchOutcome.AWAY_WIN,
    }[result]


def canonicalize_football_data_match(
    match: FootballDataMatch,
    teams: TeamRegistry,
) -> Fixture:
    """Convert one final Premier League source row into a canonical fixture."""

    if match.division != "E0":
        msg = f"unsupported Football-Data division: {match.division}"
        raise CanonicalizationError(msg)
    home_team = teams.resolve(match.source_id, match.home_team)
    away_team = teams.resolve(match.source_id, match.away_team)
    kickoff_time = match.kickoff_time or _DATE_ONLY_ANCHOR
    kickoff_precision = (
        KickoffPrecision.EXACT
        if match.kickoff_time is not None
        else KickoffPrecision.DATE_ONLY
    )
    local_kickoff = datetime.combine(
        match.match_date,
        kickoff_time,
        tzinfo=_FOOTBALL_DATA_TIMEZONE,
    )
    kickoff_at = local_kickoff.astimezone(UTC)
    season_id = f"{match.season_start:04d}-{match.season_end:04d}"
    half_time_score = None
    if (
        match.half_time_home_goals is not None
        and match.half_time_away_goals is not None
    ):
        half_time_score = FixtureScore(
            home=match.half_time_home_goals,
            away=match.half_time_away_goals,
        )

    return Fixture(
        id=canonical_fixture_id(
            PREMIER_LEAGUE_COMPETITION_ID,
            season_id,
            home_team.id,
            away_team.id,
        ),
        competition_id=PREMIER_LEAGUE_COMPETITION_ID,
        season_id=season_id,
        kickoff_at=kickoff_at,
        kickoff_precision=kickoff_precision,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        status=FixtureStatus.FINISHED,
        full_time_score=FixtureScore(
            home=match.full_time_home_goals,
            away=match.full_time_away_goals,
        ),
        half_time_score=half_time_score,
        outcome=_outcome(match.full_time_result),
        referee=match.referee,
        statistics=FixtureStatistics(
            home=TeamMatchStatistics(
                shots=match.home_shots,
                shots_on_target=match.home_shots_on_target,
                fouls=match.home_fouls,
                corners=match.home_corners,
                yellow_cards=match.home_yellow_cards,
                red_cards=match.home_red_cards,
            ),
            away=TeamMatchStatistics(
                shots=match.away_shots,
                shots_on_target=match.away_shots_on_target,
                fouls=match.away_fouls,
                corners=match.away_corners,
                yellow_cards=match.away_yellow_cards,
                red_cards=match.away_red_cards,
            ),
        ),
        source_references=(
            SourceFixtureReference(
                source_id=match.source_id,
                external_id=f"{match.source_file_id}:{match.source_row_number}",
            ),
        ),
    )
