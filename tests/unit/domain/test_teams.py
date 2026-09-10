"""Tests for canonical team identity and alias resolution."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.teams import (
    CanonicalTeam,
    TeamAlias,
    TeamRegistry,
    TeamRegistryDocument,
    TeamRegistryValidationError,
    UnknownTeamAliasError,
    load_team_registry,
    normalize_team_name,
)


def test_loads_all_current_teams_and_resolves_source_aliases() -> None:
    registry = load_team_registry(Path("data/reference/teams.json"))

    assert len(registry.teams) == 34
    assert registry.resolve("football-data-uk", "Man United").name == (
        "Manchester United"
    )
    assert registry.resolve("football-data-uk", "  MAN   UNITED ").slug == (
        "manchester-united"
    )
    assert registry.resolve("football-data-uk", "Nott'm Forest").name == (
        "Nottingham Forest"
    )
    assert registry.resolve("football-data-uk", "Leicester").name == ("Leicester City")


def test_normalize_team_name_handles_unicode_and_whitespace() -> None:
    assert normalize_team_name("  MAN\u00a0  United ") == "man united"


def test_unknown_alias_fails_loudly() -> None:
    registry = load_team_registry(Path("data/reference/teams.json"))

    with pytest.raises(UnknownTeamAliasError, match="Unlisted FC"):
        registry.resolve("football-data-uk", "Unlisted FC")


def _team(team_id: str, slug: str, alias: str) -> CanonicalTeam:
    return CanonicalTeam(
        id=UUID(team_id),
        slug=slug,
        name=slug,
        country_code="ENG",
        aliases=(TeamAlias(source_id="source", external_name=alias),),
    )


def test_registry_rejects_duplicate_aliases() -> None:
    first = _team("00000000-0000-0000-0000-000000000001", "first", "Same")
    second = _team("00000000-0000-0000-0000-000000000002", "second", " same ")
    document = TeamRegistryDocument(schema_version=1, teams=(first, second))

    with pytest.raises(TeamRegistryValidationError, match="duplicate alias"):
        TeamRegistry(document)


def test_document_rejects_duplicate_canonical_ids() -> None:
    first = _team("00000000-0000-0000-0000-000000000001", "first", "First")
    second = _team("00000000-0000-0000-0000-000000000001", "second", "Second")

    with pytest.raises(ValidationError, match="IDs must be unique"):
        TeamRegistryDocument(schema_version=1, teams=(first, second))


def test_document_rejects_duplicate_slugs() -> None:
    first = _team("00000000-0000-0000-0000-000000000001", "same", "First")
    second = _team("00000000-0000-0000-0000-000000000002", "same", "Second")

    with pytest.raises(ValidationError, match="slugs must be unique"):
        TeamRegistryDocument(schema_version=1, teams=(first, second))
