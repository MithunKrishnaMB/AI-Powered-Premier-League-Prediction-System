"""Tests for Step 4.6 immutable table updates and ranking."""

from uuid import UUID

import pytest

from pl_platform.domain.simulation import (
    LeagueTableState,
    PlayedFixture,
    Scoreline,
    SimulationContractError,
    TeamTableRow,
)
from pl_platform.simulation.table import (
    UnresolvedTableTieError,
    apply_match_result,
    build_league_table,
    rank_final_table,
)
from tests.unit.simulation.helpers import TEAM_IDS


def match(
    identity: int,
    home_index: int,
    away_index: int,
    home_goals: int,
    away_goals: int,
) -> PlayedFixture:
    return PlayedFixture(
        fixture_id=UUID(int=identity),
        home_team_id=TEAM_IDS[home_index],
        away_team_id=TEAM_IDS[away_index],
        scoreline=Scoreline(home_goals=home_goals, away_goals=away_goals),
    )


@pytest.mark.parametrize(
    ("score", "home_points", "away_points", "home_result", "away_result"),
    (
        ((2, 1), 3, 0, "won", "lost"),
        ((1, 1), 1, 1, "drawn", "drawn"),
        ((0, 2), 0, 3, "lost", "won"),
    ),
)
def test_table_update_applies_result_points_and_goals(
    score: tuple[int, int],
    home_points: int,
    away_points: int,
    home_result: str,
    away_result: str,
) -> None:
    table = apply_match_result(
        build_league_table(tuple(reversed(TEAM_IDS))),
        match(100, 0, 1, *score),
    )
    home = table.rows[0]
    away = table.rows[1]

    assert home.points == home_points
    assert away.points == away_points
    assert getattr(home, home_result) == 1
    assert getattr(away, away_result) == 1
    assert home.goals_for == score[0]
    assert away.goals_for == score[1]


def test_table_ledger_is_canonical_and_order_independent() -> None:
    results = (
        match(102, 2, 3, 0, 1),
        match(101, 0, 1, 2, 2),
    )

    assert build_league_table(TEAM_IDS, results) == build_league_table(
        TEAM_IDS,
        tuple(reversed(results)),
    )


def test_table_rejects_duplicate_fixture_and_unknown_team() -> None:
    result = match(101, 0, 1, 1, 0)
    table = apply_match_result(build_league_table(TEAM_IDS), result)
    with pytest.raises(SimulationContractError, match="applied twice"):
        apply_match_result(table, result)

    unknown = PlayedFixture(
        fixture_id=UUID(int=102),
        home_team_id=UUID(int=999),
        away_team_id=TEAM_IDS[0],
        scoreline=Scoreline(home_goals=0, away_goals=0),
    )
    with pytest.raises(SimulationContractError, match="outside the table"):
        build_league_table(TEAM_IDS, (unknown,))


def test_table_contract_rejects_rows_that_disagree_with_ledger() -> None:
    table = build_league_table(TEAM_IDS, (match(101, 0, 1, 1, 0),))
    payload = table.model_dump(mode="python")
    payload["rows"][0]["points"] = 0
    payload["rows"][0]["won"] = 0
    payload["rows"][0]["lost"] = 1

    with pytest.raises(ValueError, match="fixture ledger"):
        LeagueTableState.model_validate(payload)


def test_primary_final_ranking_orders_points_without_hidden_fallback() -> None:
    results = tuple(
        match(1000 + home * 20 + away, home, away, 1, 0)
        for home in range(20)
        for away in range(home + 1, 20)
    )
    ranked = rank_final_table(build_league_table(TEAM_IDS, results))

    assert ranked.rows[0].team_id == TEAM_IDS[0]
    assert ranked.rows[-1].team_id == TEAM_IDS[-1]
    assert tuple(row.position for row in ranked.rows) == tuple(range(1, 21))


def _constructed_tied_table(matches: tuple[PlayedFixture, ...]) -> LeagueTableState:
    tied = TeamTableRow(
        team_id=TEAM_IDS[0],
        played=38,
        won=10,
        drawn=5,
        lost=23,
        goals_for=40,
        goals_against=40,
        points=35,
    )
    rows = [
        tied,
        tied.model_copy(update={"team_id": TEAM_IDS[1]}),
    ]
    rows.extend(
        TeamTableRow(
            team_id=team_id,
            played=38,
            won=index,
            drawn=0,
            lost=38 - index,
            goals_for=index,
            goals_against=38 - index,
            points=3 * index,
        )
        for index, team_id in enumerate(TEAM_IDS[2:], start=1)
    )
    return LeagueTableState.model_construct(
        team_ids=TEAM_IDS,
        matches=matches,
        rows=tuple(rows),
    )


def test_head_to_head_points_break_primary_tie() -> None:
    table = _constructed_tied_table((match(101, 0, 1, 1, 0),))
    ranked = rank_final_table(table)
    positions = {row.team_id: row for row in ranked.rows}

    assert positions[TEAM_IDS[0]].position < positions[TEAM_IDS[1]].position
    assert positions[TEAM_IDS[0]].head_to_head_points == 3


@pytest.mark.parametrize(
    ("first_goals_for", "first_goals_against", "second_goals_for", "criterion"),
    (
        (41, 40, 40, "goal_difference"),
        (41, 41, 40, "goals_scored"),
    ),
)
def test_goal_statistics_break_points_tie_before_head_to_head(
    first_goals_for: int,
    first_goals_against: int,
    second_goals_for: int,
    criterion: str,
) -> None:
    table = _constructed_tied_table(())
    rows = list(table.rows)
    rows[0] = rows[0].model_copy(
        update={
            "goals_for": first_goals_for,
            "goals_against": first_goals_against,
        }
    )
    rows[1] = rows[1].model_copy(
        update={
            "goals_for": second_goals_for,
            "goals_against": 40,
        }
    )
    changed = table.model_copy(update={"rows": tuple(rows)})

    ranked = rank_final_table(changed)
    positions = {row.team_id: row.position for row in ranked.rows}

    assert positions[TEAM_IDS[0]] < positions[TEAM_IDS[1]], criterion


def test_head_to_head_away_goals_break_equal_points() -> None:
    table = _constructed_tied_table(
        (
            match(101, 0, 1, 1, 0),
            match(102, 1, 0, 2, 1),
        )
    )
    ranked = rank_final_table(table)
    positions = {row.team_id: row for row in ranked.rows}

    assert positions[TEAM_IDS[0]].position < positions[TEAM_IDS[1]].position
    assert positions[TEAM_IDS[0]].head_to_head_away_goals == 1
    assert positions[TEAM_IDS[1]].head_to_head_away_goals == 0


def test_residual_official_tie_requires_external_playoff() -> None:
    table = _constructed_tied_table(
        (
            match(101, 0, 1, 0, 0),
            match(102, 1, 0, 0, 0),
        )
    )

    with pytest.raises(UnresolvedTableTieError, match="playoff"):
        rank_final_table(table)
