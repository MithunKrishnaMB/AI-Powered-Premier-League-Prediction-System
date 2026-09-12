"""Tests for leakage-safe rolling, performance, and context features."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from pl_platform.domain.features import PointInTimeFeatureRow, PredictorScalar
from pl_platform.domain.fixtures import KickoffPrecision
from pl_platform.features.engine import (
    FeatureBuildError,
    build_point_in_time_feature_rows,
)
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
    make_statistics,
)


def _values(row: PointInTimeFeatureRow) -> dict[str, PredictorScalar]:
    return {predictor.name: predictor.value for predictor in row.predictors.values}


def test_same_date_rows_use_pre_batch_state_before_updates() -> None:
    first = make_fixture(
        1,
        datetime(2025, 8, 2, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        home_goals=2,
        away_goals=0,
        kickoff_precision=KickoffPrecision.DATE_ONLY,
        statistics=make_statistics(),
    )
    same_date = make_fixture(
        2,
        datetime(2025, 8, 2, 17, tzinfo=UTC),
        TEAM_IDS[2],
        TEAM_IDS[3],
        home_goals=0,
        away_goals=1,
        statistics=make_statistics(),
    )
    later = make_fixture(
        3,
        datetime(2025, 8, 9, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
        home_goals=1,
        away_goals=1,
        statistics=make_statistics(),
    )

    rows = build_point_in_time_feature_rows(
        (later, same_date, first),
        make_season(),
        make_provenance(),
    )

    assert tuple(row.fixture_id.int for row in rows) == (1, 2, 3)
    assert _values(rows[0])["home_prior_matches"] == 0
    assert _values(rows[1])["home_prior_matches"] == 0
    later_values = _values(rows[2])
    assert later_values["home_prior_matches"] == 1
    assert later_values["home_prior_points"] == 3
    assert later_values["away_prior_matches"] == 1
    assert later_values["away_prior_points"] == 0
    assert later_values["season_prior_fixtures"] == 2


def test_current_label_never_changes_current_predictors() -> None:
    kickoff = datetime(2025, 8, 2, 15, tzinfo=UTC)
    home_win = make_fixture(
        1,
        kickoff,
        TEAM_IDS[0],
        TEAM_IDS[1],
        home_goals=3,
        away_goals=0,
    )
    away_win = make_fixture(
        1,
        kickoff,
        TEAM_IDS[0],
        TEAM_IDS[1],
        home_goals=0,
        away_goals=3,
    )

    (home_win_row,) = build_point_in_time_feature_rows(
        (home_win,), make_season(), make_provenance()
    )
    (away_win_row,) = build_point_in_time_feature_rows(
        (away_win,), make_season(), make_provenance()
    )

    assert home_win_row.predictors == away_win_row.predictors
    assert home_win_row.id == away_win_row.id
    assert home_win_row.training_label != away_win_row.training_label


def test_form_window_excludes_older_results_and_rolls_performance() -> None:
    start = datetime(2025, 8, 1, 15, tzinfo=UTC)
    fixtures = []
    for index in range(6):
        fixtures.append(
            make_fixture(
                index + 1,
                start + timedelta(days=index * 3),
                TEAM_IDS[0],
                TEAM_IDS[index + 1],
                home_goals=2 if index == 0 else 1,
                away_goals=0 if index == 0 else 1,
                statistics=make_statistics(
                    home_shots=10 if index == 0 else 5,
                    away_shots=4,
                ),
            )
        )
    target = make_fixture(
        7,
        start + timedelta(days=18),
        TEAM_IDS[0],
        TEAM_IDS[7],
        statistics=make_statistics(),
    )

    rows = build_point_in_time_feature_rows(
        (*fixtures, target), make_season(), make_provenance()
    )
    target_values = _values(rows[-1])

    assert target_values["home_prior_matches"] == 6
    assert target_values["home_prior_points"] == 8
    assert target_values["home_form_5_matches"] == 5
    assert target_values["home_form_5_points"] == 5
    assert target_values["home_form_5_draw_rate"] == 1.0
    assert target_values["home_prior_goals_for_per_match"] == pytest.approx(7 / 6)
    assert target_values["home_form_5_goals_for_per_match"] == 1.0
    assert target_values["home_prior_shots_for_observations"] == 6
    assert target_values["home_prior_shots_for_per_observed_match"] == pytest.approx(
        35 / 6
    )
    assert target_values["home_form_5_shots_for_per_observed_match"] == 5.0
    assert target_values["home_form_5_fouls_for_per_observed_match"] == 11.0


def test_missing_statistics_stay_missing_instead_of_becoming_zero() -> None:
    first = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        statistics=None,
    )
    target = make_fixture(
        2,
        datetime(2025, 8, 8, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
        statistics=make_statistics(),
    )

    rows = build_point_in_time_feature_rows(
        (first, target), make_season(), make_provenance()
    )
    target_values = _values(rows[-1])

    assert target_values["home_prior_goals_for_per_match"] == 1.0
    assert target_values["home_prior_shots_for_observations"] == 0
    assert target_values["home_prior_shots_for_per_observed_match"] is None
    assert target_values["home_form_5_shots_for_per_observed_match"] is None


def test_schedule_venue_promotion_and_season_context_are_point_in_time() -> None:
    first = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[4],
        home_goals=2,
        away_goals=0,
    )
    target = make_fixture(
        2,
        datetime(2025, 8, 6, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )

    rows = build_point_in_time_feature_rows(
        (target, first), make_season(), make_provenance()
    )
    values = _values(rows[-1])

    assert values["home_rest_days"] == 5
    assert values["home_matches_last_7_days"] == 1
    assert values["home_matches_last_14_days"] == 1
    assert values["home_prior_home_matches"] == 1
    assert values["home_prior_home_points_per_match"] == 3.0
    assert values["home_prior_home_win_rate"] == 1.0
    assert values["away_rest_days"] is None
    assert values["away_prior_away_matches"] == 0
    assert values["away_prior_away_points_per_match"] is None
    assert values["home_is_promoted"] is True
    assert values["away_is_promoted"] is True
    assert values["season_prior_fixtures"] == 1
    assert values["season_progress"] == pytest.approx(1 / 380)


@pytest.mark.parametrize(
    ("fixture_changes", "provenance_changes", "message"),
    [
        ({"competition_id": "other-league"}, {}, "competition does not match"),
        ({"season_id": "2024-2025"}, {}, "season does not match"),
        ({"away_team_id": UUID(int=99)}, {}, "outside the season"),
        ({"finished": False}, {}, "must be finished"),
        ({"source_id": "other-source"}, {}, "not traceable"),
        ({}, {"competition_id": "other-league"}, "competition does not match"),
        ({}, {"season_id": "2024-2025"}, "season does not match"),
    ],
)
def test_rejects_inputs_without_consistent_canonical_lineage(
    fixture_changes: dict[str, object],
    provenance_changes: dict[str, str],
    message: str,
) -> None:
    fixture_arguments: dict[str, object] = {
        "fixture_number": 1,
        "kickoff_at": datetime(2025, 8, 1, 15, tzinfo=UTC),
        "home_team_id": TEAM_IDS[0],
        "away_team_id": TEAM_IDS[1],
    }
    fixture_arguments.update(fixture_changes)
    fixture = make_fixture(**fixture_arguments)  # type: ignore[arg-type]

    with pytest.raises(FeatureBuildError, match=message):
        build_point_in_time_feature_rows(
            (fixture,),
            make_season(),
            make_provenance(**provenance_changes),
        )
