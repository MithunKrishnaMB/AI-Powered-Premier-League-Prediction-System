"""Tests for deterministic and conservative fixture batching."""

from datetime import UTC, datetime

import pytest

from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.features.chronology import (
    ChronologyError,
    chronological_fixture_batches,
)
from tests.unit.features.helpers import TEAM_IDS, make_fixture


def test_orders_exact_fixtures_and_batches_identical_kickoffs() -> None:
    later = make_fixture(
        3,
        datetime(2025, 8, 2, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )
    same_time_larger_id = make_fixture(
        2,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[2],
        TEAM_IDS[3],
    )
    same_time_smaller_id = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[4],
        TEAM_IDS[5],
    )

    batches = chronological_fixture_batches(
        (later, same_time_larger_id, same_time_smaller_id)
    )

    assert tuple(fixture.id.int for fixture in batches[0].fixtures) == (1, 2)
    assert batches[0].feature_cutoff_at == datetime(2025, 8, 1, 15, tzinfo=UTC)
    assert not batches[0].is_date_only_batch
    assert batches[1].fixtures == (later,)


def test_date_only_fixture_batches_every_fixture_on_its_date() -> None:
    date_only = make_fixture(
        2,
        datetime(2025, 8, 2, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        kickoff_precision=KickoffPrecision.DATE_ONLY,
    )
    exact = make_fixture(
        1,
        datetime(2025, 8, 2, 17, tzinfo=UTC),
        TEAM_IDS[2],
        TEAM_IDS[3],
    )

    (batch,) = chronological_fixture_batches((date_only, exact))

    assert tuple(fixture.id.int for fixture in batch.fixtures) == (1, 2)
    assert batch.feature_cutoff_at == datetime(
        2025, 8, 1, 22, 59, 59, 999999, tzinfo=UTC
    )
    assert batch.is_date_only_batch


def test_rejects_duplicate_fixture_identity() -> None:
    fixture = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )

    with pytest.raises(ChronologyError, match="occurs more than once"):
        chronological_fixture_batches((fixture, fixture))


def test_empty_input_has_no_batches() -> None:
    assert chronological_fixture_batches(()) == ()


def test_rejects_competition_without_registered_calendar_timezone() -> None:
    fixture = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        competition_id="other-league",
    )

    with pytest.raises(ChronologyError, match="unsupported competition chronology"):
        chronological_fixture_batches((fixture,))
