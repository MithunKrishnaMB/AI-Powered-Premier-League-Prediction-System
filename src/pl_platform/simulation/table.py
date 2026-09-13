"""Immutable Premier League table updates and official final ranking rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.domain.simulation import (
    LeagueTableState,
    PlayedFixture,
    RankedLeagueTable,
    RankedTableRow,
    SimulationContractError,
    TeamTableRow,
)


class UnresolvedTableTieError(SimulationContractError):
    """Official statistics cannot separate teams without a prescribed playoff."""


def _canonical_team_ids(team_ids: Sequence[UUID]) -> tuple[UUID, ...]:
    ordered = tuple(sorted(team_ids, key=lambda value: value.int))
    if len(ordered) != 20 or len(set(ordered)) != 20:
        raise SimulationContractError("league table requires exactly 20 unique teams")
    return ordered


def _aggregate_rows(
    team_ids: tuple[UUID, ...],
    matches: tuple[PlayedFixture, ...],
) -> tuple[TeamTableRow, ...]:
    values = {
        team_id: {
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
        }
        for team_id in team_ids
    }
    for match in matches:
        if match.home_team_id not in values or match.away_team_id not in values:
            raise SimulationContractError("match references a team outside the table")
        home = values[match.home_team_id]
        away = values[match.away_team_id]
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += match.scoreline.home_goals
        home["goals_against"] += match.scoreline.away_goals
        away["goals_for"] += match.scoreline.away_goals
        away["goals_against"] += match.scoreline.home_goals
        if match.scoreline.outcome == MatchOutcome.HOME_WIN:
            home["won"] += 1
            home["points"] += 3
            away["lost"] += 1
        elif match.scoreline.outcome == MatchOutcome.AWAY_WIN:
            away["won"] += 1
            away["points"] += 3
            home["lost"] += 1
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    return tuple(
        TeamTableRow(team_id=team_id, **values[team_id]) for team_id in team_ids
    )


def build_league_table(
    team_ids: Sequence[UUID],
    matches: Sequence[PlayedFixture] = (),
) -> LeagueTableState:
    """Build canonical table state from a fixture ledger."""

    ordered_teams = _canonical_team_ids(team_ids)
    ordered_matches = tuple(sorted(matches, key=lambda match: match.fixture_id.int))
    if len({match.fixture_id for match in ordered_matches}) != len(ordered_matches):
        raise SimulationContractError("a fixture result cannot be applied twice")
    rows = _aggregate_rows(ordered_teams, ordered_matches)
    return LeagueTableState(
        team_ids=ordered_teams,
        matches=ordered_matches,
        rows=rows,
    )


def apply_match_result(
    table: LeagueTableState,
    match: PlayedFixture,
) -> LeagueTableState:
    """Return new table state after one previously unseen result."""

    if match.fixture_id in {existing.fixture_id for existing in table.matches}:
        raise SimulationContractError("a fixture result cannot be applied twice")
    return build_league_table(table.team_ids, (*table.matches, match))


def _head_to_head_values(
    team_ids: frozenset[UUID],
    matches: tuple[PlayedFixture, ...],
) -> dict[UUID, tuple[int, int]]:
    points: defaultdict[UUID, int] = defaultdict(int)
    away_goals: defaultdict[UUID, int] = defaultdict(int)
    for match in matches:
        if match.home_team_id not in team_ids or match.away_team_id not in team_ids:
            continue
        away_goals[match.away_team_id] += match.scoreline.away_goals
        if match.scoreline.outcome == MatchOutcome.HOME_WIN:
            points[match.home_team_id] += 3
        elif match.scoreline.outcome == MatchOutcome.AWAY_WIN:
            points[match.away_team_id] += 3
        else:
            points[match.home_team_id] += 1
            points[match.away_team_id] += 1
    return {team_id: (points[team_id], away_goals[team_id]) for team_id in team_ids}


def rank_final_table(table: LeagueTableState) -> RankedLeagueTable:
    """Apply official statistical tiebreakers and reject an unresolved playoff."""

    primary_groups: defaultdict[tuple[int, int, int], list[TeamTableRow]] = defaultdict(
        list
    )
    for row in table.rows:
        primary_groups[(row.points, row.goal_difference, row.goals_for)].append(row)

    ordered_rows: list[tuple[TeamTableRow, int, int]] = []
    for primary_key in sorted(primary_groups, reverse=True):
        group = primary_groups[primary_key]
        if len(group) == 1:
            ordered_rows.append((group[0], 0, 0))
            continue
        head_to_head = _head_to_head_values(
            frozenset(row.team_id for row in group),
            table.matches,
        )
        secondary_groups: defaultdict[tuple[int, int], list[TeamTableRow]] = (
            defaultdict(list)
        )
        for row in group:
            secondary_groups[head_to_head[row.team_id]].append(row)
        unresolved = [rows for rows in secondary_groups.values() if len(rows) > 1]
        if unresolved:
            team_list = ", ".join(
                str(row.team_id)
                for rows in unresolved
                for row in sorted(rows, key=lambda value: value.team_id.int)
            )
            raise UnresolvedTableTieError(
                f"official table statistics require a playoff to separate: {team_list}"
            )
        for secondary_key in sorted(secondary_groups, reverse=True):
            row = secondary_groups[secondary_key][0]
            ordered_rows.append((row, *secondary_key))

    ranked = tuple(
        RankedTableRow(
            **row.model_dump(),
            position=position,
            head_to_head_points=head_to_head_points,
            head_to_head_away_goals=head_to_head_away_goals,
        )
        for position, (row, head_to_head_points, head_to_head_away_goals) in enumerate(
            ordered_rows,
            start=1,
        )
    )
    return RankedLeagueTable(rows=ranked)
