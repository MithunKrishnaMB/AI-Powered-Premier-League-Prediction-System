"""Tests for explicit leakage-safe season-opening priors."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.features import PredictorScalar
from pl_platform.domain.fixtures import Fixture
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonEntryStatus,
    SeasonTeamMembership,
)
from pl_platform.features.engine import build_point_in_time_feature_rows
from pl_platform.features.priors import (
    FIXED_POINTS_PER_MATCH,
    OpeningPriorError,
    OpeningPriorSource,
    SeasonOpeningPrior,
    build_season_opening_priors,
)
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
)


def _previous_season() -> PremierLeagueSeason:
    previous_team_ids = (*TEAM_IDS[3:], UUID(int=21), UUID(int=22), UUID(int=23))
    return PremierLeagueSeason(
        id="2024-2025",
        competition_id="eng-premier-league",
        starts_on=date(2024, 8, 1),
        ends_on=date(2025, 5, 25),
        completed=True,
        memberships=tuple(
            SeasonTeamMembership(
                team_id=team_id,
                entry_status=(
                    SeasonEntryStatus.PROMOTED
                    if index >= 17
                    else SeasonEntryStatus.CONTINUED
                ),
                previous_competition_id=("eng-championship" if index >= 17 else None),
            )
            for index, team_id in enumerate(previous_team_ids)
        ),
    )


def _previous_fixtures() -> tuple[Fixture, ...]:
    team_ids = tuple(_previous_season().team_ids)
    ordered = tuple(sorted(team_ids))
    return tuple(
        make_fixture(
            index + 100,
            datetime(2025, 5, index + 1, 15, tzinfo=UTC),
            ordered[index * 2],
            ordered[index * 2 + 1],
            home_goals=2,
            away_goals=0,
            season_id="2024-2025",
        )
        for index in range(10)
    )


def test_first_tracked_season_uses_fixed_neutral_priors() -> None:
    priors = build_season_opening_priors(make_season())

    assert set(priors) == set(TEAM_IDS)
    assert all(
        prior.source == OpeningPriorSource.FIXED_BASELINE for prior in priors.values()
    )
    assert priors[TEAM_IDS[0]].points_per_match == FIXED_POINTS_PER_MATCH
    assert priors[TEAM_IDS[0]].reference_season_id is None


def test_continuing_teams_use_their_history_and_promoted_teams_use_league() -> None:
    previous_season = _previous_season()
    fixtures = _previous_fixtures()

    priors = build_season_opening_priors(
        make_season(),
        fixtures,
        previous_season,
    )

    continued = priors[TEAM_IDS[3]]
    promoted = priors[TEAM_IDS[0]]
    assert continued.source == OpeningPriorSource.PREVIOUS_TEAM
    assert continued.reference_matches == 1
    assert continued.reference_season_id == "2024-2025"
    assert promoted.source == OpeningPriorSource.PREVIOUS_LEAGUE
    assert promoted.reference_matches == 20
    assert promoted.reference_season_id == "2024-2025"


def test_opening_priors_are_explicit_and_blend_only_prior_current_results() -> None:
    priors = build_season_opening_priors(
        make_season(),
        _previous_fixtures(),
        _previous_season(),
    )
    first = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[3],
        TEAM_IDS[0],
        home_goals=0,
        away_goals=3,
    )
    later = make_fixture(
        2,
        datetime(2025, 8, 8, 15, tzinfo=UTC),
        TEAM_IDS[3],
        TEAM_IDS[1],
    )

    rows = build_point_in_time_feature_rows(
        (later, first),
        make_season(),
        make_provenance(),
        opening_priors=priors,
    )
    first_values: dict[str, PredictorScalar] = {
        item.name: item.value for item in rows[0].predictors.values
    }
    later_values: dict[str, PredictorScalar] = {
        item.name: item.value for item in rows[1].predictors.values
    }

    assert first_values["home_opening_prior_from_previous_team"] is True
    assert first_values["away_opening_prior_from_previous_league"] is True
    assert (
        first_values["home_blended_points_per_match"]
        == first_values["home_opening_prior_points_per_match"]
    )
    assert (
        later_values["home_blended_points_per_match"]
        != first_values["home_blended_points_per_match"]
    )


def test_prior_contract_and_transition_inputs_reject_ambiguity() -> None:
    with pytest.raises(ValidationError, match="rates must sum"):
        SeasonOpeningPrior(
            source=OpeningPriorSource.FIXED_BASELINE,
            reference_matches=0,
            points_per_match=1.0,
            win_rate=0.5,
            draw_rate=0.5,
            loss_rate=0.5,
            goals_for_per_match=1.5,
            goals_against_per_match=1.5,
        )
    with pytest.raises(OpeningPriorError, match="supplied together"):
        build_season_opening_priors(
            make_season(),
            _previous_fixtures(),
        )


def test_rejects_current_or_invalid_prior_season_data() -> None:
    previous_season = _previous_season()
    current_fixture = make_fixture(
        999,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[3],
        TEAM_IDS[4],
    )

    with pytest.raises(OpeningPriorError, match="does not match prior season"):
        build_season_opening_priors(
            make_season(),
            (current_fixture,),
            previous_season,
        )
    overlapping = previous_season.model_copy(update={"ends_on": date(2025, 8, 1)})
    with pytest.raises(OpeningPriorError, match="finish before"):
        build_season_opening_priors(
            make_season(),
            _previous_fixtures(),
            overlapping,
        )
