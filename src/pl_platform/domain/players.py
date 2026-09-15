"""Canonical player identities and reviewed exact provider resolution."""

import json
import unicodedata
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlayerRegistryValidationError(ValueError):
    """A player registry contains duplicate or ambiguous reviewed evidence."""


class UnknownPlayerAliasError(LookupError):
    """A provider player has no reviewed canonical identity."""


class PlayerIdentityConflictError(ValueError):
    """Reviewed provider ID and name evidence identify different players."""


class PlayerAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    external_name: str = Field(min_length=1)
    external_id: str | None = Field(default=None, min_length=1)

    @field_validator("external_id")
    @classmethod
    def external_id_must_be_exact_and_printable(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("player external ID must be trimmed and printable")
        return value


class CanonicalPlayer(BaseModel):
    """Reviewed platform identity; never derived from a provider identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str = Field(min_length=1)
    aliases: tuple[PlayerAlias, ...] = Field(min_length=1)


class PlayerRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    players: tuple[CanonicalPlayer, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_identifiers_must_be_unique(self) -> Self:
        identifiers = tuple(player.id for player in self.players)
        slugs = tuple(player.slug for player in self.players)
        if len(identifiers) != len(set(identifiers)):
            raise PlayerRegistryValidationError("canonical player IDs must be unique")
        if len(slugs) != len(set(slugs)):
            raise PlayerRegistryValidationError("canonical player slugs must be unique")
        return self


def normalize_player_name(value: str) -> str:
    """Normalize harmless Unicode/whitespace variation without fuzzy matching."""

    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


class PlayerRegistry:
    """Resolve only reviewed exact IDs or normalized exact aliases."""

    def __init__(self, document: PlayerRegistryDocument) -> None:
        self.schema_version = document.schema_version
        self.players = document.players
        aliases: dict[tuple[str, str], CanonicalPlayer] = {}
        external_ids: dict[tuple[str, str], CanonicalPlayer] = {}
        for player in self.players:
            for alias in player.aliases:
                alias_key = (
                    alias.source_id,
                    normalize_player_name(alias.external_name),
                )
                if alias_key in aliases:
                    raise PlayerRegistryValidationError(
                        "duplicate player alias for one provider source"
                    )
                aliases[alias_key] = player
                if alias.external_id is not None:
                    external_key = (alias.source_id, alias.external_id)
                    if external_key in external_ids:
                        raise PlayerRegistryValidationError(
                            "duplicate player external ID for one provider source"
                        )
                    external_ids[external_key] = player
        self._aliases = aliases
        self._external_ids = external_ids

    def resolve_provider_player(
        self,
        source_id: str,
        external_id: str,
        external_name: str,
    ) -> CanonicalPlayer:
        """Resolve reviewed evidence and reject disagreement or unknown identity."""

        by_id = self._external_ids.get((source_id, external_id))
        by_name = self._aliases.get((source_id, normalize_player_name(external_name)))
        if by_id is not None and by_name is not None and by_id.id != by_name.id:
            raise PlayerIdentityConflictError(
                "provider player ID and alias identify different players"
            )
        resolved = by_id or by_name
        if resolved is None:
            raise UnknownPlayerAliasError(
                "unknown provider player identity; reviewed mapping required"
            )
        return resolved


def load_player_registry(path: Path) -> PlayerRegistry:
    """Load a reviewed UTF-8 player registry without provider inference."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return PlayerRegistry(PlayerRegistryDocument.model_validate(payload))
