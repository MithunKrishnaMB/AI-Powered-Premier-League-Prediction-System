"""Competition-level integrity checks for canonical fixture datasets."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pl_platform.domain.fixtures import Fixture, FixtureStatus, KickoffPrecision
from pl_platform.domain.seasons import PremierLeagueSeason


class QualitySeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: QualitySeverity
    message: str
    fixture_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class FixtureQualityReport:
    checked_fixtures: int
    issues: tuple[QualityIssue, ...]

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity == QualitySeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity == QualitySeverity.WARNING
        )

    @property
    def is_valid(self) -> bool:
        return not self.errors


class DataQualityError(ValueError):
    """A canonical dataset failed one or more mandatory integrity checks."""

    def __init__(self, report: FixtureQualityReport) -> None:
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in report.errors)
        super().__init__(summary)
        self.report = report


def _issue(
    issues: list[QualityIssue],
    code: str,
    message: str,
    fixture_id: UUID | None = None,
    *,
    severity: QualitySeverity = QualitySeverity.ERROR,
) -> None:
    issues.append(
        QualityIssue(
            code=code,
            severity=severity,
            message=message,
            fixture_id=fixture_id,
        )
    )


def validate_premier_league_fixtures(
    fixtures: tuple[Fixture, ...],
    season: PremierLeagueSeason,
) -> FixtureQualityReport:
    """Validate identity, membership, schedule, status and completeness."""

    issues: list[QualityIssue] = []
    fixture_ids: set[UUID] = set()
    home_away_pairs: set[tuple[UUID, UUID]] = set()
    home_counts: Counter[UUID] = Counter()
    away_counts: Counter[UUID] = Counter()

    for fixture in fixtures:
        if fixture.id in fixture_ids:
            _issue(
                issues,
                "duplicate_fixture_id",
                f"fixture ID {fixture.id} occurs more than once",
                fixture.id,
            )
        fixture_ids.add(fixture.id)

        pair = (fixture.home_team_id, fixture.away_team_id)
        if pair in home_away_pairs:
            _issue(
                issues,
                "duplicate_home_away_pair",
                "home/away pairing occurs more than once in the season",
                fixture.id,
            )
        home_away_pairs.add(pair)

        if fixture.competition_id != season.competition_id:
            _issue(
                issues,
                "competition_mismatch",
                f"fixture competition is {fixture.competition_id!r}",
                fixture.id,
            )
        if fixture.season_id != season.id:
            _issue(
                issues,
                "season_mismatch",
                f"fixture season is {fixture.season_id!r}",
                fixture.id,
            )

        for team_id in (fixture.home_team_id, fixture.away_team_id):
            if team_id not in season.team_ids:
                _issue(
                    issues,
                    "unknown_season_team",
                    f"team {team_id} is not registered for {season.id}",
                    fixture.id,
                )

        kickoff_date = fixture.kickoff_at.date()
        if not season.starts_on <= kickoff_date <= season.ends_on:
            _issue(
                issues,
                "kickoff_outside_season",
                f"kickoff {kickoff_date} is outside the registered season window",
                fixture.id,
            )

        if season.completed and fixture.status != FixtureStatus.FINISHED:
            _issue(
                issues,
                "unfinished_completed_season",
                f"completed season contains status {fixture.status}",
                fixture.id,
            )

        if fixture.kickoff_precision == KickoffPrecision.DATE_ONLY:
            _issue(
                issues,
                "date_only_kickoff",
                "source provides a match date but no exact kickoff time",
                fixture.id,
                severity=QualitySeverity.WARNING,
            )

        if fixture.statistics is None:
            _issue(
                issues,
                "missing_match_statistics",
                "optional match statistics are unavailable",
                fixture.id,
                severity=QualitySeverity.WARNING,
            )

        home_counts[fixture.home_team_id] += 1
        away_counts[fixture.away_team_id] += 1

    team_count = len(season.team_ids)
    expected_fixture_count = team_count * (team_count - 1)
    if len(fixtures) != expected_fixture_count:
        _issue(
            issues,
            "fixture_count",
            f"expected {expected_fixture_count} fixtures, found {len(fixtures)}",
        )

    expected_venue_count = team_count - 1
    for team_id in season.team_ids:
        if home_counts[team_id] != expected_venue_count:
            _issue(
                issues,
                "home_fixture_count",
                f"team {team_id} has {home_counts[team_id]} home fixtures; "
                f"expected {expected_venue_count}",
            )
        if away_counts[team_id] != expected_venue_count:
            _issue(
                issues,
                "away_fixture_count",
                f"team {team_id} has {away_counts[team_id]} away fixtures; "
                f"expected {expected_venue_count}",
            )

    return FixtureQualityReport(
        checked_fixtures=len(fixtures),
        issues=tuple(issues),
    )
