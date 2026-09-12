"""Deterministic fixture ordering with conservative simultaneous batches."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pl_platform.domain.fixtures import Fixture, KickoffPrecision


class ChronologyError(ValueError):
    """Fixtures cannot be assigned an unambiguous point-in-time chronology."""


_PREMIER_LEAGUE_TIMEZONE = ZoneInfo("Europe/London")


@dataclass(frozen=True, slots=True)
class FixtureBatch:
    """Fixtures that must all observe state from before any batch update."""

    feature_cutoff_at: datetime
    fixtures: tuple[Fixture, ...]
    is_date_only_batch: bool


def _before_date(fixture_date: date) -> datetime:
    local_date_start = datetime.combine(
        fixture_date,
        time.min,
        tzinfo=_PREMIER_LEAGUE_TIMEZONE,
    ).astimezone(UTC)
    return local_date_start - timedelta(microseconds=1)


def fixture_competition_date(fixture: Fixture) -> date:
    """Return the fixture's Premier League calendar date."""

    if fixture.competition_id != "eng-premier-league":
        msg = f"unsupported competition chronology: {fixture.competition_id!r}"
        raise ChronologyError(msg)
    return fixture.kickoff_at.astimezone(_PREMIER_LEAGUE_TIMEZONE).date()


def chronological_fixture_batches(
    fixtures: Sequence[Fixture],
) -> tuple[FixtureBatch, ...]:
    """Group fixtures into deterministic, leakage-safe chronological batches.

    Any Premier League calendar date containing at least one date-only record
    becomes one simultaneous batch. This also absorbs exact-time records on that
    date, because their results cannot safely order a fixture whose time is
    unknown. Dates containing only exact kickoffs are grouped by identical
    timestamp.
    """

    fixture_ids: set[UUID] = set()
    fixtures_by_date: dict[date, list[Fixture]] = defaultdict(list)
    for fixture in fixtures:
        if fixture.id in fixture_ids:
            msg = f"fixture ID {fixture.id} occurs more than once"
            raise ChronologyError(msg)
        fixture_ids.add(fixture.id)
        fixtures_by_date[fixture_competition_date(fixture)].append(fixture)

    batches: list[FixtureBatch] = []
    for fixture_date in sorted(fixtures_by_date):
        date_fixtures = fixtures_by_date[fixture_date]
        if any(
            fixture.kickoff_precision == KickoffPrecision.DATE_ONLY
            for fixture in date_fixtures
        ):
            batches.append(
                FixtureBatch(
                    feature_cutoff_at=_before_date(fixture_date),
                    fixtures=tuple(sorted(date_fixtures, key=lambda item: item.id)),
                    is_date_only_batch=True,
                )
            )
            continue

        fixtures_by_kickoff: dict[datetime, list[Fixture]] = defaultdict(list)
        for fixture in date_fixtures:
            fixtures_by_kickoff[fixture.kickoff_at].append(fixture)
        for kickoff_at in sorted(fixtures_by_kickoff):
            batches.append(
                FixtureBatch(
                    feature_cutoff_at=kickoff_at,
                    fixtures=tuple(
                        sorted(
                            fixtures_by_kickoff[kickoff_at],
                            key=lambda item: item.id,
                        )
                    ),
                    is_date_only_batch=False,
                )
            )

    return tuple(batches)
