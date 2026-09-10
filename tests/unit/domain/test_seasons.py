"""Tests for Premier League season membership and transitions."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from pl_platform.domain.seasons import (
    SeasonEntryStatus,
    SeasonRegistry,
    SeasonRegistryDocument,
    SeasonRegistryValidationError,
    load_season_registry,
)
from pl_platform.domain.teams import load_team_registry

TEAMS_PATH = Path("data/reference/teams.json")
SEASONS_PATH = Path("data/reference/seasons.json")


def _season_payload() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(SEASONS_PATH.read_text(encoding="utf-8")),
    )


def test_loads_season_and_promoted_memberships() -> None:
    teams = load_team_registry(TEAMS_PATH)
    registry = load_season_registry(SEASONS_PATH, teams)

    season = registry.get("2025-2026")
    promoted_names = {
        team.name for team in teams.teams if team.id in season.promoted_team_ids
    }

    assert len(season.team_ids) == 20
    assert promoted_names == {"Burnley", "Leeds United", "Sunderland"}
    assert season.completed is True
    assert len(registry.seasons) == 11


def test_oldest_season_has_reviewed_promotions() -> None:
    teams = load_team_registry(TEAMS_PATH)
    registry = load_season_registry(SEASONS_PATH, teams)
    season = registry.get("2015-2016")
    promoted_names = {
        team.name for team in teams.teams if team.id in season.promoted_team_ids
    }

    assert promoted_names == {"AFC Bournemouth", "Norwich City", "Watford"}


def test_missing_season_has_descriptive_error() -> None:
    teams = load_team_registry(TEAMS_PATH)
    registry = load_season_registry(SEASONS_PATH, teams)

    with pytest.raises(KeyError, match="2014-2015"):
        registry.get("2014-2015")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda season: season.update({"ends_on": "2015-01-01"}), "end must follow"),
        (lambda season: season.update({"id": "2024-2025"}), "ID must match"),
        (lambda season: season["memberships"].pop(), "exactly 20"),
        (
            lambda season: season["memberships"].append(
                season["memberships"][0].copy()
            ),
            "exactly 20",
        ),
    ],
)
def test_rejects_invalid_season_structure(
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = _season_payload()
    seasons = payload["seasons"]
    assert isinstance(seasons, list)
    mutation(seasons[0])

    with pytest.raises(ValidationError, match=message):
        SeasonRegistryDocument.model_validate(payload)


def test_rejects_inconsistent_promotion_metadata() -> None:
    payload = _season_payload()
    seasons = payload["seasons"]
    assert isinstance(seasons, list)
    memberships = seasons[0]["memberships"]
    memberships[0]["entry_status"] = SeasonEntryStatus.PROMOTED

    with pytest.raises(ValidationError, match="previous_competition_id"):
        SeasonRegistryDocument.model_validate(payload)


def test_rejects_unknown_canonical_team() -> None:
    teams = load_team_registry(TEAMS_PATH)
    payload = _season_payload()
    seasons = payload["seasons"]
    assert isinstance(seasons, list)
    seasons[0]["memberships"][0]["team_id"] = "00000000-0000-0000-0000-000000000000"
    document = SeasonRegistryDocument.model_validate(payload)

    with pytest.raises(SeasonRegistryValidationError, match="unknown team IDs"):
        SeasonRegistry(document, teams)
