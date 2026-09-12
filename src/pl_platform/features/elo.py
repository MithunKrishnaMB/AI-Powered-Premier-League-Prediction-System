"""Deterministic point-in-time Elo initialization, prediction and updates."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from pl_platform.domain.fixtures import Fixture, FixtureStatus
from pl_platform.domain.ratings import EloMatchPrediction, EloParameters
from pl_platform.domain.seasons import PremierLeagueSeason, SeasonEntryStatus

DEFAULT_ELO_PARAMETERS = EloParameters()


class EloError(ValueError):
    """Elo state or a fixture violates point-in-time rating semantics."""


def initialize_season_ratings(
    season: PremierLeagueSeason,
    previous_final_ratings: Mapping[UUID, float] | None = None,
    parameters: EloParameters = DEFAULT_ELO_PARAMETERS,
) -> dict[UUID, float]:
    """Initialize the season, regressing continuing clubs toward the baseline."""

    if previous_final_ratings is None:
        return {team_id: parameters.initial_rating for team_id in season.team_ids}

    ratings: dict[UUID, float] = {}
    for membership in season.memberships:
        if membership.entry_status == SeasonEntryStatus.PROMOTED:
            ratings[membership.team_id] = parameters.initial_rating
            continue
        previous_rating = previous_final_ratings.get(membership.team_id)
        if previous_rating is None:
            msg = "continued team has no previous-season Elo rating"
            raise EloError(msg)
        ratings[membership.team_id] = parameters.initial_rating + (
            parameters.season_retention * (previous_rating - parameters.initial_rating)
        )
    return ratings


def predict_elo_match(
    home_team_id: UUID,
    away_team_id: UUID,
    ratings: Mapping[UUID, float],
    parameters: EloParameters = DEFAULT_ELO_PARAMETERS,
) -> EloMatchPrediction:
    """Return the expected score from the unchanged pre-match rating state."""

    try:
        home_rating = ratings[home_team_id]
        away_rating = ratings[away_team_id]
    except KeyError as exc:
        msg = f"Elo state has no rating for team {exc.args[0]}"
        raise EloError(msg) from exc
    exponent = (away_rating - home_rating - parameters.home_advantage) / (
        parameters.rating_scale
    )
    bounded_exponent = min(12.0, max(-12.0, exponent))
    home_expected = 1.0 / (1.0 + 10.0**bounded_exponent)
    return EloMatchPrediction(
        home_rating=float(home_rating),
        away_rating=float(away_rating),
        home_expected_score=home_expected,
        away_expected_score=1.0 - home_expected,
    )


def update_elo_batch(
    ratings: Mapping[UUID, float],
    fixtures: Sequence[Fixture],
    parameters: EloParameters = DEFAULT_ELO_PARAMETERS,
) -> dict[UUID, float]:
    """Apply every fixture delta to one shared pre-batch rating snapshot."""

    updated = dict(ratings)
    deltas = {team_id: 0.0 for team_id in ratings}
    for fixture in fixtures:
        if fixture.status != FixtureStatus.FINISHED or fixture.full_time_score is None:
            msg = "Elo updates require a completed fixture score"
            raise EloError(msg)
        prediction = predict_elo_match(
            fixture.home_team_id,
            fixture.away_team_id,
            ratings,
            parameters,
        )
        if fixture.full_time_score.home > fixture.full_time_score.away:
            actual_home = 1.0
        elif fixture.full_time_score.home == fixture.full_time_score.away:
            actual_home = 0.5
        else:
            actual_home = 0.0
        delta = parameters.k_factor * (actual_home - prediction.home_expected_score)
        deltas[fixture.home_team_id] += delta
        deltas[fixture.away_team_id] -= delta
    for team_id, delta in deltas.items():
        updated[team_id] += delta
    return updated
