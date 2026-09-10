"""Provider-independent fixture and match-statistics contracts."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonNegativeInt = Annotated[int, Field(ge=0)]


class MatchOutcome(StrEnum):
    HOME_WIN = "home_win"
    DRAW = "draw"
    AWAY_WIN = "away_win"


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class KickoffPrecision(StrEnum):
    """How precisely the upstream source identifies a fixture kickoff."""

    EXACT = "exact"
    DATE_ONLY = "date_only"


class FixtureScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    home: NonNegativeInt
    away: NonNegativeInt

    @property
    def outcome(self) -> MatchOutcome:
        if self.home > self.away:
            return MatchOutcome.HOME_WIN
        if self.home < self.away:
            return MatchOutcome.AWAY_WIN
        return MatchOutcome.DRAW


class TeamMatchStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shots: NonNegativeInt | None = None
    shots_on_target: NonNegativeInt | None = None
    fouls: NonNegativeInt | None = None
    corners: NonNegativeInt | None = None
    yellow_cards: NonNegativeInt | None = None
    red_cards: NonNegativeInt | None = None


class FixtureStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    home: TeamMatchStatistics
    away: TeamMatchStatistics


class SourceFixtureReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1)


class Fixture(BaseModel):
    """Canonical fixture independent of provider-specific names and codes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    competition_id: str = Field(min_length=1)
    season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    kickoff_at: datetime
    kickoff_precision: KickoffPrecision = KickoffPrecision.EXACT
    home_team_id: UUID
    away_team_id: UUID
    status: FixtureStatus
    full_time_score: FixtureScore | None = None
    half_time_score: FixtureScore | None = None
    outcome: MatchOutcome | None = None
    matchweek: int | None = Field(default=None, ge=1)
    referee: str | None = None
    statistics: FixtureStatistics | None = None
    source_references: tuple[SourceFixtureReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fixture_state_must_be_consistent(self) -> Self:
        if self.kickoff_at.tzinfo is None or self.kickoff_at.utcoffset() != timedelta(
            0
        ):
            msg = "kickoff_at must be timezone-aware UTC"
            raise ValueError(msg)
        if self.home_team_id == self.away_team_id:
            msg = "home and away teams must differ"
            raise ValueError(msg)

        inactive = {
            FixtureStatus.SCHEDULED,
            FixtureStatus.POSTPONED,
            FixtureStatus.CANCELLED,
        }
        if self.status in inactive and any(
            value is not None
            for value in (self.full_time_score, self.half_time_score, self.outcome)
        ):
            msg = "inactive fixtures cannot contain a score or outcome"
            raise ValueError(msg)
        if self.status == FixtureStatus.FINISHED:
            if self.full_time_score is None or self.outcome is None:
                msg = "finished fixtures require a full-time score and outcome"
                raise ValueError(msg)
            if self.outcome != self.full_time_score.outcome:
                msg = "fixture outcome does not match the full-time score"
                raise ValueError(msg)
        if (
            self.half_time_score is not None
            and self.full_time_score is not None
            and (
                self.half_time_score.home > self.full_time_score.home
                or self.half_time_score.away > self.full_time_score.away
            )
        ):
            msg = "half-time goals cannot exceed full-time goals"
            raise ValueError(msg)
        return self
