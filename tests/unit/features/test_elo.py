"""Tests for deterministic point-in-time Elo behavior."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pl_platform.domain.ratings import EloMatchPrediction, EloParameters
from pl_platform.features.elo import (
    DEFAULT_ELO_PARAMETERS,
    EloError,
    initialize_season_ratings,
    predict_elo_match,
    update_elo_batch,
)
from tests.unit.features.helpers import TEAM_IDS, make_fixture, make_season


def test_home_advantage_changes_expected_score_without_mutating_state() -> None:
    ratings = {TEAM_IDS[0]: 1500.0, TEAM_IDS[1]: 1500.0}

    prediction = predict_elo_match(TEAM_IDS[0], TEAM_IDS[1], ratings)

    assert prediction.home_expected_score > 0.5
    assert prediction.away_expected_score == pytest.approx(
        1.0 - prediction.home_expected_score
    )
    assert ratings == {TEAM_IDS[0]: 1500.0, TEAM_IDS[1]: 1500.0}


def test_finished_result_updates_ratings_as_a_zero_sum_pair() -> None:
    ratings = {TEAM_IDS[0]: 1500.0, TEAM_IDS[1]: 1500.0}
    fixture = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        home_goals=2,
        away_goals=0,
    )

    updated = update_elo_batch(ratings, (fixture,))

    assert updated[TEAM_IDS[0]] > ratings[TEAM_IDS[0]]
    assert updated[TEAM_IDS[1]] < ratings[TEAM_IDS[1]]
    assert sum(updated.values()) == pytest.approx(sum(ratings.values()))


def test_batch_deltas_share_one_pre_batch_snapshot() -> None:
    ratings = {team_id: 1500.0 for team_id in TEAM_IDS[:3]}
    first = make_fixture(
        1,
        datetime(2025, 8, 1, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )
    second = make_fixture(
        2,
        datetime(2025, 8, 1, 12, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[2],
    )
    expected = predict_elo_match(TEAM_IDS[0], TEAM_IDS[1], ratings)
    one_delta = DEFAULT_ELO_PARAMETERS.k_factor * (1.0 - expected.home_expected_score)

    updated = update_elo_batch(ratings, (first, second))

    assert updated[TEAM_IDS[0]] == pytest.approx(1500.0 + 2.0 * one_delta)


def test_season_transition_regresses_continuing_clubs_and_resets_promoted() -> None:
    previous = {team_id: 1600.0 for team_id in TEAM_IDS}

    initialized = initialize_season_ratings(make_season(), previous)

    assert initialized[TEAM_IDS[0]] == 1500.0
    assert initialized[TEAM_IDS[3]] == 1575.0

    del previous[TEAM_IDS[3]]
    with pytest.raises(EloError, match="no previous-season"):
        initialize_season_ratings(make_season(), previous)


def test_elo_contracts_and_invalid_updates_fail_closed() -> None:
    with pytest.raises(ValidationError):
        EloParameters(k_factor=0.0)
    with pytest.raises(ValidationError, match="sum to one"):
        EloMatchPrediction(
            home_rating=1500.0,
            away_rating=1500.0,
            home_expected_score=0.6,
            away_expected_score=0.5,
        )
    with pytest.raises(EloError, match="no rating"):
        predict_elo_match(TEAM_IDS[0], TEAM_IDS[1], {TEAM_IDS[0]: 1500.0})
    unfinished = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
        finished=False,
    )
    with pytest.raises(EloError, match="completed"):
        update_elo_batch(
            {TEAM_IDS[0]: 1500.0, TEAM_IDS[1]: 1500.0},
            (unfinished,),
        )
