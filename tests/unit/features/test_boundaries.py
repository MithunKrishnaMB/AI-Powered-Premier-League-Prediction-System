"""Explicit temporal, target-leakage, and missing-data boundary tests."""

from datetime import UTC, datetime

from pl_platform.domain.features import PointInTimeFeatureRow, PredictorScalar
from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.features.engine import build_point_in_time_feature_rows
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
    make_statistics,
)


def _values(row: PointInTimeFeatureRow) -> dict[str, PredictorScalar]:
    return {predictor.name: predictor.value for predictor in row.predictors.values}


def test_future_and_current_targets_cannot_change_existing_predictors() -> None:
    first = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        home_goals=1,
        away_goals=0,
        statistics=make_statistics(home_shots=10),
    )
    second = make_fixture(
        2,
        datetime(2025, 8, 8, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
        home_goals=2,
        away_goals=0,
        statistics=make_statistics(home_shots=12),
    )
    changed_second = make_fixture(
        2,
        second.kickoff_at,
        TEAM_IDS[0],
        TEAM_IDS[2],
        home_goals=0,
        away_goals=4,
        statistics=make_statistics(home_shots=1, away_shots=20),
    )

    baseline = build_point_in_time_feature_rows(
        (first, second), make_season(), make_provenance()
    )
    changed = build_point_in_time_feature_rows(
        (first, changed_second), make_season(), make_provenance()
    )

    assert tuple(row.predictors for row in baseline) == tuple(
        row.predictors for row in changed
    )
    assert tuple(row.id for row in baseline) == tuple(row.id for row in changed)
    assert baseline[1].training_label != changed[1].training_label


def test_shared_team_observes_pre_date_state_for_entire_date_only_batch() -> None:
    first = make_fixture(
        1,
        datetime(2025, 8, 2, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        kickoff_precision=KickoffPrecision.DATE_ONLY,
    )
    same_date = make_fixture(
        2,
        datetime(2025, 8, 2, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
        kickoff_precision=KickoffPrecision.DATE_ONLY,
    )

    rows = build_point_in_time_feature_rows(
        (first, same_date), make_season(), make_provenance()
    )

    assert _values(rows[0])["home_prior_matches"] == 0
    assert _values(rows[1])["home_prior_matches"] == 0
    assert rows[0].feature_cutoff_at == rows[1].feature_cutoff_at


def test_exact_later_kickoff_observes_earlier_exact_result() -> None:
    earlier = make_fixture(
        1,
        datetime(2025, 8, 2, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )
    later = make_fixture(
        2,
        datetime(2025, 8, 2, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
    )

    rows = build_point_in_time_feature_rows(
        (later, earlier), make_season(), make_provenance()
    )

    assert _values(rows[1])["home_prior_matches"] == 1
    assert rows[1].feature_cutoff_at == later.kickoff_at


def test_date_only_cutoff_tracks_london_daylight_saving_boundary() -> None:
    summer = make_fixture(
        1,
        datetime(2025, 8, 2, 11, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        kickoff_precision=KickoffPrecision.DATE_ONLY,
    )
    winter = make_fixture(
        2,
        datetime(2026, 1, 2, 12, tzinfo=UTC),
        TEAM_IDS[2],
        TEAM_IDS[3],
        kickoff_precision=KickoffPrecision.DATE_ONLY,
    )

    rows = build_point_in_time_feature_rows(
        (winter, summer), make_season(), make_provenance()
    )

    assert rows[0].feature_cutoff_at == datetime(
        2025, 8, 1, 22, 59, 59, 999999, tzinfo=UTC
    )
    assert rows[1].feature_cutoff_at == datetime(
        2026, 1, 1, 23, 59, 59, 999999, tzinfo=UTC
    )


def test_approved_predictor_schema_excludes_labels_and_bookmaker_fields() -> None:
    fixture = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )

    (row,) = build_point_in_time_feature_rows(
        (fixture,), make_season(), make_provenance()
    )
    names = {predictor.name for predictor in row.predictors.values}

    assert names.isdisjoint({"outcome", "home_goals", "away_goals", "training_label"})
    assert not any("odds" in name or "bookmaker" in name for name in names)
    assert row.training_label is not None
