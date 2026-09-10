"""Typed parsing for Football-Data.co.uk historical CSV rows."""

import csv
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pl_platform.ingestion.download import verify_existing_file
from pl_platform.ingestion.manifest import HistoricalDataManifest

NonNegativeInt = Annotated[int, Field(ge=0)]


class SourceParseError(ValueError):
    """A source row cannot be converted into the typed source contract."""


class FootballDataResult(StrEnum):
    """Result codes used by Football-Data CSV files."""

    HOME = "H"
    DRAW = "D"
    AWAY = "A"


class FootballDataMatch(BaseModel):
    """One validated match while retaining Football-Data naming semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_file_id: str
    source_row_number: int = Field(ge=2)
    division: str
    season_start: int
    season_end: int
    match_date: date
    kickoff_time: time | None
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    full_time_home_goals: NonNegativeInt
    full_time_away_goals: NonNegativeInt
    full_time_result: FootballDataResult
    half_time_home_goals: NonNegativeInt | None
    half_time_away_goals: NonNegativeInt | None
    half_time_result: FootballDataResult | None
    referee: str | None
    home_shots: NonNegativeInt | None
    away_shots: NonNegativeInt | None
    home_shots_on_target: NonNegativeInt | None
    away_shots_on_target: NonNegativeInt | None
    home_fouls: NonNegativeInt | None
    away_fouls: NonNegativeInt | None
    home_corners: NonNegativeInt | None
    away_corners: NonNegativeInt | None
    home_yellow_cards: NonNegativeInt | None
    away_yellow_cards: NonNegativeInt | None
    home_red_cards: NonNegativeInt | None
    away_red_cards: NonNegativeInt | None
    additional_fields: dict[str, str | None]

    @model_validator(mode="after")
    def scores_must_match_results(self) -> Self:
        expected_full_time = _result_for_score(
            self.full_time_home_goals,
            self.full_time_away_goals,
        )
        if self.full_time_result != expected_full_time:
            msg = "full-time result does not match the full-time score"
            raise ValueError(msg)

        half_time_values = (
            self.half_time_home_goals,
            self.half_time_away_goals,
            self.half_time_result,
        )
        if any(value is None for value in half_time_values):
            if not all(value is None for value in half_time_values):
                msg = (
                    "half-time score and result must either all be present "
                    "or all be absent"
                )
                raise ValueError(msg)
        elif (
            self.half_time_home_goals is not None
            and self.half_time_away_goals is not None
            and self.half_time_result
            != _result_for_score(
                self.half_time_home_goals,
                self.half_time_away_goals,
            )
        ):
            msg = "half-time result does not match the half-time score"
            raise ValueError(msg)

        if self.home_team == self.away_team:
            msg = "home and away teams must differ"
            raise ValueError(msg)
        return self


_PARSED_COLUMNS = frozenset(
    {
        "Div",
        "Date",
        "Time",
        "HomeTeam",
        "AwayTeam",
        "FTHG",
        "FTAG",
        "FTR",
        "HTHG",
        "HTAG",
        "HTR",
        "Referee",
        "HS",
        "AS",
        "HST",
        "AST",
        "HF",
        "AF",
        "HC",
        "AC",
        "HY",
        "AY",
        "HR",
        "AR",
    }
)
_REQUIRED_COLUMNS = frozenset(
    {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}
)


def _result_for_score(home_goals: int, away_goals: int) -> FootballDataResult:
    if home_goals > away_goals:
        return FootballDataResult.HOME
    if home_goals < away_goals:
        return FootballDataResult.AWAY
    return FootballDataResult.DRAW


def _required(row: dict[str, str | None], column: str, row_number: int) -> str:
    value = row.get(column)
    if value is None or not value.strip():
        msg = f"row {row_number} has no value for required column {column}"
        raise SourceParseError(msg)
    return value.strip()


def _optional(row: dict[str, str | None], column: str) -> str | None:
    value = row.get(column)
    if value is None or not value.strip():
        return None
    return value.strip()


def _integer(
    row: dict[str, str | None],
    column: str,
    row_number: int,
    *,
    required: bool,
) -> int | None:
    value = _required(row, column, row_number) if required else _optional(row, column)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = f"row {row_number} has invalid integer {value!r} in column {column}"
        raise SourceParseError(msg) from exc
    if parsed < 0:
        msg = f"row {row_number} has negative value in column {column}"
        raise SourceParseError(msg)
    return parsed


def _date(value: str, row_number: int) -> date:
    for date_format in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    msg = f"row {row_number} has unsupported date {value!r}"
    raise SourceParseError(msg)


def _time(value: str | None, row_number: int) -> time | None:
    if value is None:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        msg = f"row {row_number} has unsupported kickoff time {value!r}"
        raise SourceParseError(msg) from exc


def _parse_row(
    row: dict[str, str | None],
    row_number: int,
    *,
    source_id: str,
    source_file_id: str,
    season_start: int,
    season_end: int,
) -> FootballDataMatch:
    full_time_home_goals = _integer(row, "FTHG", row_number, required=True)
    full_time_away_goals = _integer(row, "FTAG", row_number, required=True)
    assert full_time_home_goals is not None
    assert full_time_away_goals is not None

    return FootballDataMatch(
        source_id=source_id,
        source_file_id=source_file_id,
        source_row_number=row_number,
        division=_required(row, "Div", row_number),
        season_start=season_start,
        season_end=season_end,
        match_date=_date(_required(row, "Date", row_number), row_number),
        kickoff_time=_time(_optional(row, "Time"), row_number),
        home_team=_required(row, "HomeTeam", row_number),
        away_team=_required(row, "AwayTeam", row_number),
        full_time_home_goals=full_time_home_goals,
        full_time_away_goals=full_time_away_goals,
        full_time_result=FootballDataResult(_required(row, "FTR", row_number)),
        half_time_home_goals=_integer(row, "HTHG", row_number, required=False),
        half_time_away_goals=_integer(row, "HTAG", row_number, required=False),
        half_time_result=(
            FootballDataResult(value) if (value := _optional(row, "HTR")) else None
        ),
        referee=_optional(row, "Referee"),
        home_shots=_integer(row, "HS", row_number, required=False),
        away_shots=_integer(row, "AS", row_number, required=False),
        home_shots_on_target=_integer(row, "HST", row_number, required=False),
        away_shots_on_target=_integer(row, "AST", row_number, required=False),
        home_fouls=_integer(row, "HF", row_number, required=False),
        away_fouls=_integer(row, "AF", row_number, required=False),
        home_corners=_integer(row, "HC", row_number, required=False),
        away_corners=_integer(row, "AC", row_number, required=False),
        home_yellow_cards=_integer(row, "HY", row_number, required=False),
        away_yellow_cards=_integer(row, "AY", row_number, required=False),
        home_red_cards=_integer(row, "HR", row_number, required=False),
        away_red_cards=_integer(row, "AR", row_number, required=False),
        additional_fields={
            key: value.strip() if value and value.strip() else None
            for key, value in row.items()
            if key not in _PARSED_COLUMNS
        },
    )


def parse_football_data_csv(
    path: Path,
    manifest: HistoricalDataManifest,
    entry_id: str,
) -> tuple[FootballDataMatch, ...]:
    """Verify and parse one downloaded Football-Data CSV."""

    entry = manifest.get_file(entry_id)
    verify_existing_file(entry, path)

    with path.open(encoding=entry.encoding, newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = set(reader.fieldnames or ())
        missing_columns = sorted(_REQUIRED_COLUMNS - columns)
        if missing_columns:
            msg = f"source file is missing columns: {', '.join(missing_columns)}"
            raise SourceParseError(msg)
        parsed_matches: list[FootballDataMatch] = []
        for row_number, row in enumerate(reader, start=2):
            if not any(value not in (None, "") for value in row.values()):
                continue
            try:
                match = _parse_row(
                    row,
                    row_number,
                    source_id=manifest.source.id,
                    source_file_id=entry.id,
                    season_start=entry.season_start,
                    season_end=entry.season_end,
                )
            except SourceParseError:
                raise
            except (ValidationError, ValueError) as exc:
                msg = f"row {row_number} violates the Football-Data schema"
                raise SourceParseError(msg) from exc
            parsed_matches.append(match)
        matches = tuple(parsed_matches)

    if len(matches) != entry.expected_rows:
        msg = (
            f"parsed row count mismatch for {entry.id}: expected "
            f"{entry.expected_rows}, received {len(matches)}"
        )
        raise SourceParseError(msg)
    return matches
