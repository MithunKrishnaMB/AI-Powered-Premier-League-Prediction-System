"""Tests for provider-to-canonical fixture transformation."""

from datetime import UTC, date, time
from pathlib import Path

import pytest

from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.domain.teams import (
    TeamRegistry,
    UnknownTeamAliasError,
    load_team_registry,
)
from pl_platform.ingestion.football_data import (
    FootballDataMatch,
    FootballDataResult,
)
from pl_platform.ingestion.normalize import (
    CanonicalizationError,
    canonicalize_football_data_match,
)


def _match(**changes: object) -> FootballDataMatch:
    payload: dict[str, object] = {
        "source_id": "football-data-uk",
        "source_file_id": "epl-2025-2026",
        "source_row_number": 2,
        "division": "E0",
        "season_start": 2025,
        "season_end": 2026,
        "match_date": date(2025, 8, 15),
        "kickoff_time": time(20, 0),
        "home_team": "Man United",
        "away_team": "Nott'm Forest",
        "full_time_home_goals": 2,
        "full_time_away_goals": 1,
        "full_time_result": FootballDataResult.HOME,
        "half_time_home_goals": 1,
        "half_time_away_goals": 0,
        "half_time_result": FootballDataResult.HOME,
        "referee": "A Referee",
        "home_shots": 10,
        "away_shots": 8,
        "home_shots_on_target": 4,
        "away_shots_on_target": 2,
        "home_fouls": 7,
        "away_fouls": 9,
        "home_corners": 5,
        "away_corners": 3,
        "home_yellow_cards": 1,
        "away_yellow_cards": 2,
        "home_red_cards": 0,
        "away_red_cards": 0,
        "additional_fields": {"B365H": "1.80"},
    }
    payload.update(changes)
    return FootballDataMatch.model_validate(payload)


def _teams() -> TeamRegistry:
    return load_team_registry(Path("data/reference/teams.json"))


def test_canonicalizes_aliases_time_and_statistics() -> None:
    fixture = canonicalize_football_data_match(_match(), _teams())
    repeated = canonicalize_football_data_match(_match(), _teams())

    assert fixture.id == repeated.id
    assert fixture.season_id == "2025-2026"
    assert fixture.kickoff_at.tzinfo is UTC
    assert fixture.kickoff_at.hour == 19
    assert fixture.outcome == MatchOutcome.HOME_WIN
    assert fixture.statistics is not None
    assert fixture.statistics.home.shots == 10
    assert fixture.source_references[0].external_id == "epl-2025-2026:2"


def test_rejects_unknown_alias() -> None:
    with pytest.raises(UnknownTeamAliasError, match="Unknown FC"):
        canonicalize_football_data_match(
            _match(home_team="Unknown FC"),
            _teams(),
        )


def test_rejects_unsupported_division() -> None:
    with pytest.raises(CanonicalizationError, match="unsupported"):
        canonicalize_football_data_match(_match(division="E1"), _teams())


def test_rejects_missing_kickoff_time() -> None:
    with pytest.raises(CanonicalizationError, match="no kickoff time"):
        canonicalize_football_data_match(_match(kickoff_time=None), _teams())
