"""Leakage-safe season-opening prior construction."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isclose
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.fixtures import Fixture, FixtureStatus
from pl_platform.domain.seasons import PremierLeagueSeason, SeasonEntryStatus

OPENING_PRIOR_SCHEMA_VERSION: Final = 1
OPENING_PRIOR_WEIGHT_MATCHES: Final = 5
FIXED_RESULT_RATE: Final = 1.0 / 3.0
FIXED_POINTS_PER_MATCH: Final = 4.0 / 3.0
FIXED_GOALS_PER_MATCH: Final = 1.5

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Rate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class OpeningPriorError(ValueError):
    """Season history cannot form an unambiguous opening prior."""


class OpeningPriorSource(StrEnum):
    FIXED_BASELINE = "fixed_baseline"
    PREVIOUS_LEAGUE = "previous_league"
    PREVIOUS_TEAM = "previous_team"


class SeasonOpeningPrior(BaseModel):
    """One team's point-in-time prior fixed before a season begins."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = OPENING_PRIOR_SCHEMA_VERSION
    source: OpeningPriorSource
    reference_season_id: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{4}$",
    )
    reference_matches: NonNegativeInt
    weight_matches: Literal[5] = OPENING_PRIOR_WEIGHT_MATCHES
    points_per_match: NonNegativeFloat
    win_rate: Rate
    draw_rate: Rate
    loss_rate: Rate
    goals_for_per_match: NonNegativeFloat
    goals_against_per_match: NonNegativeFloat

    @model_validator(mode="after")
    def source_and_rates_must_be_consistent(self) -> Self:
        is_fixed = self.source == OpeningPriorSource.FIXED_BASELINE
        if is_fixed != (self.reference_season_id is None):
            msg = (
                "fixed priors cannot reference a season; historical priors require one"
            )
            raise ValueError(msg)
        if is_fixed != (self.reference_matches == 0):
            msg = "fixed priors require zero reference matches"
            raise ValueError(msg)
        if not isclose(
            self.win_rate + self.draw_rate + self.loss_rate,
            1.0,
            abs_tol=1e-12,
        ):
            msg = "opening-prior result rates must sum to one"
            raise ValueError(msg)
        expected_points = 3.0 * self.win_rate + self.draw_rate
        if not isclose(self.points_per_match, expected_points, abs_tol=1e-12):
            msg = "opening-prior points per match must match result rates"
            raise ValueError(msg)
        return self


@dataclass(slots=True)
class _Summary:
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0

    def observe(self, goals_for: int, goals_against: int) -> None:
        self.matches += 1
        self.goals_for += goals_for
        self.goals_against += goals_against
        if goals_for > goals_against:
            self.wins += 1
            self.points += 3
        elif goals_for == goals_against:
            self.draws += 1
            self.points += 1
        else:
            self.losses += 1


def _fixed_prior() -> SeasonOpeningPrior:
    return SeasonOpeningPrior(
        source=OpeningPriorSource.FIXED_BASELINE,
        reference_matches=0,
        points_per_match=FIXED_POINTS_PER_MATCH,
        win_rate=FIXED_RESULT_RATE,
        draw_rate=FIXED_RESULT_RATE,
        loss_rate=FIXED_RESULT_RATE,
        goals_for_per_match=FIXED_GOALS_PER_MATCH,
        goals_against_per_match=FIXED_GOALS_PER_MATCH,
    )


def _prior_from_summary(
    summary: _Summary,
    source: Literal[
        OpeningPriorSource.PREVIOUS_LEAGUE,
        OpeningPriorSource.PREVIOUS_TEAM,
    ],
    reference_season_id: str,
) -> SeasonOpeningPrior:
    if summary.matches == 0:
        msg = "historical opening priors require at least one reference match"
        raise OpeningPriorError(msg)
    return SeasonOpeningPrior(
        source=source,
        reference_season_id=reference_season_id,
        reference_matches=summary.matches,
        points_per_match=summary.points / summary.matches,
        win_rate=summary.wins / summary.matches,
        draw_rate=summary.draws / summary.matches,
        loss_rate=summary.losses / summary.matches,
        goals_for_per_match=summary.goals_for / summary.matches,
        goals_against_per_match=summary.goals_against / summary.matches,
    )


def _previous_summaries(
    fixtures: Sequence[Fixture],
    season: PremierLeagueSeason,
) -> tuple[dict[UUID, _Summary], _Summary]:
    summaries = {team_id: _Summary() for team_id in season.team_ids}
    league = _Summary()
    for fixture in fixtures:
        if fixture.competition_id != season.competition_id:
            msg = "opening-prior fixture competition does not match prior season"
            raise OpeningPriorError(msg)
        if fixture.season_id != season.id:
            msg = "opening-prior fixture does not match prior season"
            raise OpeningPriorError(msg)
        if (
            fixture.home_team_id not in summaries
            or fixture.away_team_id not in summaries
        ):
            msg = "opening-prior fixture contains a team outside prior membership"
            raise OpeningPriorError(msg)
        if fixture.status != FixtureStatus.FINISHED or fixture.full_time_score is None:
            msg = "opening priors require completed prior-season scores"
            raise OpeningPriorError(msg)
        home_goals = fixture.full_time_score.home
        away_goals = fixture.full_time_score.away
        summaries[fixture.home_team_id].observe(home_goals, away_goals)
        summaries[fixture.away_team_id].observe(away_goals, home_goals)
        league.observe(home_goals, away_goals)
        league.observe(away_goals, home_goals)
    return summaries, league


def build_season_opening_priors(
    season: PremierLeagueSeason,
    previous_fixtures: Sequence[Fixture] | None = None,
    previous_season: PremierLeagueSeason | None = None,
) -> dict[UUID, SeasonOpeningPrior]:
    """Build priors from information available strictly before season start."""

    if (previous_fixtures is None) != (previous_season is None):
        msg = "previous fixtures and season must be supplied together"
        raise OpeningPriorError(msg)
    if previous_season is None or previous_fixtures is None:
        return {team_id: _fixed_prior() for team_id in season.team_ids}
    if previous_season.ends_on >= season.starts_on:
        msg = "opening-prior season must finish before the current season starts"
        raise OpeningPriorError(msg)

    summaries, league_summary = _previous_summaries(
        previous_fixtures,
        previous_season,
    )
    league_prior = _prior_from_summary(
        league_summary,
        OpeningPriorSource.PREVIOUS_LEAGUE,
        previous_season.id,
    )
    previous_team_ids = previous_season.team_ids
    priors: dict[UUID, SeasonOpeningPrior] = {}
    for membership in season.memberships:
        appeared_previously = membership.team_id in previous_team_ids
        if membership.entry_status == SeasonEntryStatus.CONTINUED:
            if not appeared_previously:
                msg = "continued team is absent from the previous season"
                raise OpeningPriorError(msg)
            priors[membership.team_id] = _prior_from_summary(
                summaries[membership.team_id],
                OpeningPriorSource.PREVIOUS_TEAM,
                previous_season.id,
            )
        else:
            if appeared_previously:
                msg = "promoted team unexpectedly appears in the previous season"
                raise OpeningPriorError(msg)
            priors[membership.team_id] = league_prior
    return priors
