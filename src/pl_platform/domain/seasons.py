"""Premier League season membership and transition contracts."""

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.teams import TeamRegistry


class SeasonRegistryValidationError(ValueError):
    """Season membership is incomplete, ambiguous, or references unknown teams."""


class SeasonEntryStatus(StrEnum):
    CONTINUED = "continued"
    PROMOTED = "promoted"


class SeasonTeamMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: UUID
    entry_status: SeasonEntryStatus
    previous_competition_id: str | None = None

    @model_validator(mode="after")
    def promotion_metadata_must_be_consistent(self) -> Self:
        if (
            self.entry_status == SeasonEntryStatus.PROMOTED
            and self.previous_competition_id is None
        ):
            msg = "promoted teams require previous_competition_id"
            raise ValueError(msg)
        if (
            self.entry_status == SeasonEntryStatus.CONTINUED
            and self.previous_competition_id is not None
        ):
            msg = "continued teams cannot declare previous_competition_id"
            raise ValueError(msg)
        return self


class PremierLeagueSeason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^\d{4}-\d{4}$")
    competition_id: Literal["eng-premier-league"]
    starts_on: date
    ends_on: date
    completed: bool
    memberships: tuple[SeasonTeamMembership, ...]

    @model_validator(mode="after")
    def season_structure_must_be_valid(self) -> Self:
        if self.ends_on <= self.starts_on:
            msg = "season end must follow season start"
            raise ValueError(msg)
        expected_id = f"{self.starts_on.year:04d}-{self.ends_on.year:04d}"
        if self.id != expected_id:
            msg = "season ID must match start and end years"
            raise ValueError(msg)

        team_ids = [membership.team_id for membership in self.memberships]
        if len(team_ids) != 20:
            msg = "a Premier League season must contain exactly 20 teams"
            raise ValueError(msg)
        if len(team_ids) != len(set(team_ids)):
            msg = "season team memberships must be unique"
            raise ValueError(msg)

        promoted_count = sum(
            membership.entry_status == SeasonEntryStatus.PROMOTED
            for membership in self.memberships
        )
        if promoted_count != 3:
            msg = "a Premier League season must identify exactly three promoted teams"
            raise ValueError(msg)
        return self

    @property
    def team_ids(self) -> frozenset[UUID]:
        return frozenset(membership.team_id for membership in self.memberships)

    @property
    def promoted_team_ids(self) -> frozenset[UUID]:
        return frozenset(
            membership.team_id
            for membership in self.memberships
            if membership.entry_status == SeasonEntryStatus.PROMOTED
        )


class SeasonRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    seasons: tuple[PremierLeagueSeason, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def season_ids_must_be_unique(self) -> Self:
        season_ids = [season.id for season in self.seasons]
        if len(season_ids) != len(set(season_ids)):
            msg = "season IDs must be unique"
            raise ValueError(msg)
        return self


class SeasonRegistry:
    def __init__(
        self,
        document: SeasonRegistryDocument,
        teams: TeamRegistry,
    ) -> None:
        known_team_ids = {team.id for team in teams.teams}
        referenced_team_ids = {
            membership.team_id
            for season in document.seasons
            for membership in season.memberships
        }
        unknown_team_ids = referenced_team_ids - known_team_ids
        if unknown_team_ids:
            unknown = ", ".join(str(team_id) for team_id in sorted(unknown_team_ids))
            msg = f"season registry references unknown team IDs: {unknown}"
            raise SeasonRegistryValidationError(msg)

        self.schema_version = document.schema_version
        self.seasons = document.seasons
        self._by_id = {season.id: season for season in document.seasons}

    def get(self, season_id: str) -> PremierLeagueSeason:
        try:
            return self._by_id[season_id]
        except KeyError as exc:
            msg = f"season registry has no entry named {season_id!r}"
            raise KeyError(msg) from exc


def load_season_registry(path: Path, teams: TeamRegistry) -> SeasonRegistry:
    """Load season transitions and verify every canonical team reference."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    document = SeasonRegistryDocument.model_validate(payload)
    return SeasonRegistry(document, teams)
