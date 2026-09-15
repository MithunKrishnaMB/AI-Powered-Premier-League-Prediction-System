"""Current-season synchronization write-plan tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.ingestion.current import CurrentProviderCapability
from pl_platform.ingestion.current_transform import (
    CanonicalCurrentFixture,
    transform_completed_results,
    transform_current_fixtures,
    transform_current_standings,
    transform_current_teams,
)
from pl_platform.persistence.current_sync import (
    current_fixture_sync_plan,
    current_results_sync_plan,
    current_standings_sync_plan,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    PersistenceTable,
    RepositoryContractError,
)
from tests.unit.ingestion.current_helpers import (
    NOW,
    capture_for,
    registry_and_season,
)
from tests.unit.ingestion.test_current_reconciliation import (
    _resolution,
    _result_response,
    _standings_response,
)
from tests.unit.ingestion.test_current_transform import (
    _fixture,
    _fixture_response,
    _teams_response,
)


def _fixtures() -> tuple[CanonicalCurrentFixture, ...]:
    registry, season = registry_and_season()
    resolution = transform_current_teams(_teams_response(0, 1, 2), registry, season)
    observations = (
        _fixture(
            "fixture-a",
            0,
            1,
            datetime(2026, 9, 20, 11, tzinfo=UTC),
            precision=KickoffPrecision.DATE_ONLY,
        ),
        _fixture(
            "fixture-b",
            1,
            2,
            datetime(2026, 9, 20, 15, tzinfo=UTC),
        ),
    )
    return transform_current_fixtures(
        _fixture_response(observations), resolution, season
    )


def test_fixture_plan_preserves_fact_observation_batch_and_cache_provenance() -> None:
    fixtures = _fixtures()

    plan = current_fixture_sync_plan(fixtures)

    tables = tuple(row.table for row in plan.rows)
    assert plan.kind is AggregateKind.CURRENT_FIXTURES
    assert tables.count(PersistenceTable.FIXTURE) == 2
    assert tables.count(PersistenceTable.CURRENT_FIXTURE_REVISION) == 2
    assert tables.count(PersistenceTable.CURRENT_FIXTURE_OBSERVATION) == 2
    assert tables.count(PersistenceTable.CURRENT_FIXTURE_BATCH) == 1
    assert tables.count(PersistenceTable.CURRENT_FIXTURE_BATCH_MEMBER) == 2
    assert tables.count(PersistenceTable.CURRENT_FIXTURE_BATCH_PROVENANCE) == 1
    batch = next(
        row for row in plan.rows if row.table is PersistenceTable.CURRENT_FIXTURE_BATCH
    )
    values = {item.name: item.value for item in batch.values}
    assert values["batch_kind"] == "date_only_date"
    assert values["exact_kickoff_at"] is None


def test_result_and_standings_plans_are_content_derived_and_separate() -> None:
    resolution, season = _resolution()
    results = transform_completed_results(_result_response(), resolution, season)
    snapshot = transform_current_standings(_standings_response(), resolution, season)

    result_plan = current_results_sync_plan(results)
    standing_plan = current_standings_sync_plan(snapshot, results)

    assert result_plan.kind is AggregateKind.CURRENT_RESULTS
    assert any(
        row.table is PersistenceTable.CURRENT_COMPLETED_RESULT
        for row in result_plan.rows
    )
    assert any(
        row.table is PersistenceTable.CURRENT_RESULT_OBSERVATION
        for row in result_plan.rows
    )
    assert standing_plan.kind is AggregateKind.CURRENT_STANDINGS
    assert (
        sum(
            row.table is PersistenceTable.CURRENT_STANDING_ROW
            for row in standing_plan.rows
        )
        == 20
    )
    assert result_plan.objects[0].sha256 != standing_plan.objects[0].sha256


def test_empty_fixture_and_result_synchronization_fail_before_database() -> None:
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        current_fixture_sync_plan(())
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        current_results_sync_plan(())


def test_status_observation_adds_revision_without_schedule_batch() -> None:
    status = replace(
        _fixtures()[0],
        capture=capture_for(
            CurrentProviderCapability.FIXTURE_STATUS,
            1,
            retrieved_at=NOW + timedelta(minutes=1),
        ),
        status_observed_at=NOW + timedelta(seconds=30),
    )

    plan = current_fixture_sync_plan((status,))

    assert not any(
        row.table is PersistenceTable.CURRENT_FIXTURE_BATCH for row in plan.rows
    )
    observation = next(
        row
        for row in plan.rows
        if row.table is PersistenceTable.CURRENT_FIXTURE_OBSERVATION
    )
    values = {item.name: item.value for item in observation.values}
    assert values["provider_observed_at"] == NOW + timedelta(seconds=30)
