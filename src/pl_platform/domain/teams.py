"""Canonical team identities and explicit source alias resolution."""

import json
import unicodedata
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TeamRegistryValidationError(ValueError):
    """The canonical registry contains ambiguous or duplicate identities."""


class UnknownTeamAliasError(LookupError):
    """A source name has no reviewed canonical-team mapping."""


class TeamAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    external_name: str = Field(min_length=1)
    external_id: str | None = None


class CanonicalTeam(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    country_code: str = Field(pattern=r"^[A-Z]{3}$")
    aliases: tuple[TeamAlias, ...] = Field(min_length=1)


class TeamRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    teams: tuple[CanonicalTeam, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_identifiers_must_be_unique(self) -> Self:
        identifiers = [team.id for team in self.teams]
        slugs = [team.slug for team in self.teams]
        if len(identifiers) != len(set(identifiers)):
            raise TeamRegistryValidationError("canonical team IDs must be unique")
        if len(slugs) != len(set(slugs)):
            raise TeamRegistryValidationError("canonical team slugs must be unique")
        return self


def normalize_team_name(value: str) -> str:
    """Normalize harmless textual variation without applying fuzzy matching."""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


class TeamRegistry:
    """Resolve reviewed provider aliases to canonical team records."""

    def __init__(self, document: TeamRegistryDocument) -> None:
        self.schema_version = document.schema_version
        self.teams = document.teams
        aliases: dict[tuple[str, str], CanonicalTeam] = {}
        for team in self.teams:
            for alias in team.aliases:
                key = (alias.source_id, normalize_team_name(alias.external_name))
                if key in aliases:
                    msg = (
                        f"duplicate alias {alias.external_name!r} for source "
                        f"{alias.source_id!r}"
                    )
                    raise TeamRegistryValidationError(msg)
                aliases[key] = team
        self._aliases = aliases

    def resolve(self, source_id: str, external_name: str) -> CanonicalTeam:
        key = (source_id, normalize_team_name(external_name))
        try:
            return self._aliases[key]
        except KeyError as exc:
            msg = f"unknown team alias {external_name!r} for source {source_id!r}"
            raise UnknownTeamAliasError(msg) from exc


def load_team_registry(path: Path) -> TeamRegistry:
    """Load a UTF-8 JSON canonical team registry."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    document = TeamRegistryDocument.model_validate(payload)
    return TeamRegistry(document)
