"""In-memory construction of leakage-safe Premier League predictors."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal
from uuid import UUID

from pl_platform.domain.features import (
    CanonicalDatasetProvenance,
    PointInTimeFeatureRow,
    PredictorScalar,
    PredictorSet,
    PredictorValue,
    TrainingLabel,
    deterministic_feature_row_id,
)
from pl_platform.domain.fixtures import (
    Fixture,
    FixtureStatus,
    TeamMatchStatistics,
)
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.features.chronology import (
    chronological_fixture_batches,
    fixture_competition_date,
)

FORM_WINDOW_MATCHES: Final = 5
PREDICTOR_SCHEMA_ID: Final = "epl-pre-match"
PREDICTOR_SCHEMA_VERSION: Final = 1

OptionalMetric = Literal[
    "shots_for",
    "shots_against",
    "shots_on_target_for",
    "shots_on_target_against",
    "fouls_for",
    "fouls_against",
    "yellow_cards_for",
    "yellow_cards_against",
    "red_cards_for",
    "red_cards_against",
]
_OPTIONAL_METRICS: Final[tuple[OptionalMetric, ...]] = (
    "shots_for",
    "shots_against",
    "shots_on_target_for",
    "shots_on_target_against",
    "fouls_for",
    "fouls_against",
    "yellow_cards_for",
    "yellow_cards_against",
    "red_cards_for",
    "red_cards_against",
)


class FeatureBuildError(ValueError):
    """Canonical fixtures cannot safely produce the requested feature rows."""


@dataclass(frozen=True, slots=True)
class _TeamObservation:
    fixture_date: date
    was_home: bool
    points: int
    won: bool
    drew: bool
    lost: bool
    goals_for: int
    goals_against: int
    shots_for: int | None
    shots_against: int | None
    shots_on_target_for: int | None
    shots_on_target_against: int | None
    fouls_for: int | None
    fouls_against: int | None
    yellow_cards_for: int | None
    yellow_cards_against: int | None
    red_cards_for: int | None
    red_cards_against: int | None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metric_value(
    observation: _TeamObservation,
    metric: OptionalMetric,
) -> int | None:
    if metric == "shots_for":
        return observation.shots_for
    if metric == "shots_against":
        return observation.shots_against
    if metric == "shots_on_target_for":
        return observation.shots_on_target_for
    if metric == "shots_on_target_against":
        return observation.shots_on_target_against
    if metric == "fouls_for":
        return observation.fouls_for
    if metric == "fouls_against":
        return observation.fouls_against
    if metric == "yellow_cards_for":
        return observation.yellow_cards_for
    if metric == "yellow_cards_against":
        return observation.yellow_cards_against
    if metric == "red_cards_for":
        return observation.red_cards_for
    return observation.red_cards_against


def _observed_average(values: Iterable[int | None]) -> tuple[int, float | None]:
    observed = tuple(value for value in values if value is not None)
    return len(observed), _rate(sum(observed), len(observed))


def _add_result_features(
    values: dict[str, PredictorScalar],
    prefix: str,
    observations: Sequence[_TeamObservation],
) -> None:
    match_count = len(observations)
    wins = sum(observation.won for observation in observations)
    draws = sum(observation.drew for observation in observations)
    losses = sum(observation.lost for observation in observations)
    points = sum(observation.points for observation in observations)
    values.update(
        {
            f"{prefix}_prior_matches": match_count,
            f"{prefix}_prior_wins": wins,
            f"{prefix}_prior_draws": draws,
            f"{prefix}_prior_losses": losses,
            f"{prefix}_prior_points": points,
            f"{prefix}_prior_points_per_match": _rate(points, match_count),
            f"{prefix}_prior_win_rate": _rate(wins, match_count),
            f"{prefix}_prior_draw_rate": _rate(draws, match_count),
            f"{prefix}_prior_loss_rate": _rate(losses, match_count),
        }
    )

    form = observations[-FORM_WINDOW_MATCHES:]
    form_count = len(form)
    form_wins = sum(observation.won for observation in form)
    form_draws = sum(observation.drew for observation in form)
    form_losses = sum(observation.lost for observation in form)
    form_points = sum(observation.points for observation in form)
    values.update(
        {
            f"{prefix}_form_5_matches": form_count,
            f"{prefix}_form_5_points": form_points,
            f"{prefix}_form_5_points_per_match": _rate(form_points, form_count),
            f"{prefix}_form_5_win_rate": _rate(form_wins, form_count),
            f"{prefix}_form_5_draw_rate": _rate(form_draws, form_count),
            f"{prefix}_form_5_loss_rate": _rate(form_losses, form_count),
        }
    )


def _add_performance_features(
    values: dict[str, PredictorScalar],
    prefix: str,
    observations: Sequence[_TeamObservation],
) -> None:
    form = observations[-FORM_WINDOW_MATCHES:]
    prior_goals_for = tuple(observation.goals_for for observation in observations)
    form_goals_for = tuple(observation.goals_for for observation in form)
    prior_goals_against = tuple(
        observation.goals_against for observation in observations
    )
    form_goals_against = tuple(observation.goals_against for observation in form)
    for metric, prior_values, form_values in (
        ("goals_for", prior_goals_for, form_goals_for),
        ("goals_against", prior_goals_against, form_goals_against),
    ):
        values[f"{prefix}_prior_{metric}_per_match"] = _rate(
            sum(prior_values), len(prior_values)
        )
        values[f"{prefix}_form_5_{metric}_per_match"] = _rate(
            sum(form_values), len(form_values)
        )

    for metric in _OPTIONAL_METRICS:
        prior_count, prior_average = _observed_average(
            _metric_value(observation, metric) for observation in observations
        )
        form_count, form_average = _observed_average(
            _metric_value(observation, metric) for observation in form
        )
        values[f"{prefix}_prior_{metric}_observations"] = prior_count
        values[f"{prefix}_prior_{metric}_per_observed_match"] = prior_average
        values[f"{prefix}_form_5_{metric}_observations"] = form_count
        values[f"{prefix}_form_5_{metric}_per_observed_match"] = form_average


def _add_schedule_and_venue_features(
    values: dict[str, PredictorScalar],
    prefix: str,
    observations: Sequence[_TeamObservation],
    fixture_date: date,
    *,
    home_role: bool,
) -> None:
    rest_days = None
    if observations:
        rest_days = (fixture_date - observations[-1].fixture_date).days
    values[f"{prefix}_rest_days"] = rest_days
    values[f"{prefix}_matches_last_7_days"] = sum(
        0 < (fixture_date - observation.fixture_date).days <= 7
        for observation in observations
    )
    values[f"{prefix}_matches_last_14_days"] = sum(
        0 < (fixture_date - observation.fixture_date).days <= 14
        for observation in observations
    )

    venue_observations = tuple(
        observation for observation in observations if observation.was_home is home_role
    )
    venue = "home" if home_role else "away"
    venue_points = sum(observation.points for observation in venue_observations)
    venue_wins = sum(observation.won for observation in venue_observations)
    values[f"{prefix}_prior_{venue}_matches"] = len(venue_observations)
    values[f"{prefix}_prior_{venue}_points_per_match"] = _rate(
        venue_points, len(venue_observations)
    )
    values[f"{prefix}_prior_{venue}_win_rate"] = _rate(
        venue_wins, len(venue_observations)
    )


def _predictors_for_fixture(
    fixture: Fixture,
    state: dict[UUID, list[_TeamObservation]],
    season: PremierLeagueSeason,
    season_prior_fixtures: int,
) -> PredictorSet:
    values: dict[str, PredictorScalar] = {
        "away_is_promoted": fixture.away_team_id in season.promoted_team_ids,
        "home_is_promoted": fixture.home_team_id in season.promoted_team_ids,
        "season_prior_fixtures": season_prior_fixtures,
        "season_progress": season_prior_fixtures
        / (len(season.team_ids) * (len(season.team_ids) - 1)),
    }
    for prefix, team_id, home_role in (
        ("home", fixture.home_team_id, True),
        ("away", fixture.away_team_id, False),
    ):
        observations = state[team_id]
        _add_result_features(values, prefix, observations)
        _add_performance_features(values, prefix, observations)
        _add_schedule_and_venue_features(
            values,
            prefix,
            observations,
            fixture_competition_date(fixture),
            home_role=home_role,
        )

    return PredictorSet(
        schema_id=PREDICTOR_SCHEMA_ID,
        schema_version=PREDICTOR_SCHEMA_VERSION,
        values=tuple(
            PredictorValue(name=name, value=value)
            for name, value in sorted(values.items())
        ),
    )


def _team_statistics(
    fixture: Fixture,
    *,
    home: bool,
) -> tuple[TeamMatchStatistics | None, TeamMatchStatistics | None]:
    if fixture.statistics is None:
        return None, None
    if home:
        return fixture.statistics.home, fixture.statistics.away
    return fixture.statistics.away, fixture.statistics.home


def _observation(fixture: Fixture, *, home: bool) -> _TeamObservation:
    if fixture.full_time_score is None:
        msg = f"finished fixture {fixture.id} has no full-time score"
        raise FeatureBuildError(msg)
    goals_for = fixture.full_time_score.home if home else fixture.full_time_score.away
    goals_against = (
        fixture.full_time_score.away if home else fixture.full_time_score.home
    )
    if goals_for > goals_against:
        points, won, drew, lost = 3, True, False, False
    elif goals_for == goals_against:
        points, won, drew, lost = 1, False, True, False
    else:
        points, won, drew, lost = 0, False, False, True
    own_statistics, opposing_statistics = _team_statistics(fixture, home=home)
    return _TeamObservation(
        fixture_date=fixture_competition_date(fixture),
        was_home=home,
        points=points,
        won=won,
        drew=drew,
        lost=lost,
        goals_for=goals_for,
        goals_against=goals_against,
        shots_for=None if own_statistics is None else own_statistics.shots,
        shots_against=None
        if opposing_statistics is None
        else opposing_statistics.shots,
        shots_on_target_for=None
        if own_statistics is None
        else own_statistics.shots_on_target,
        shots_on_target_against=None
        if opposing_statistics is None
        else opposing_statistics.shots_on_target,
        fouls_for=None if own_statistics is None else own_statistics.fouls,
        fouls_against=None
        if opposing_statistics is None
        else opposing_statistics.fouls,
        yellow_cards_for=None
        if own_statistics is None
        else own_statistics.yellow_cards,
        yellow_cards_against=None
        if opposing_statistics is None
        else opposing_statistics.yellow_cards,
        red_cards_for=None if own_statistics is None else own_statistics.red_cards,
        red_cards_against=None
        if opposing_statistics is None
        else opposing_statistics.red_cards,
    )


def _validate_build_inputs(
    fixtures: Sequence[Fixture],
    season: PremierLeagueSeason,
    provenance: CanonicalDatasetProvenance,
) -> None:
    if provenance.competition_id != season.competition_id:
        msg = "provenance competition does not match the season"
        raise FeatureBuildError(msg)
    if provenance.season_id != season.id:
        msg = "provenance season does not match the season"
        raise FeatureBuildError(msg)
    for fixture in fixtures:
        if fixture.competition_id != season.competition_id:
            msg = f"fixture {fixture.id} competition does not match the season"
            raise FeatureBuildError(msg)
        if fixture.season_id != season.id:
            msg = f"fixture {fixture.id} season does not match the season"
            raise FeatureBuildError(msg)
        if fixture.home_team_id not in season.team_ids or fixture.away_team_id not in (
            season.team_ids
        ):
            msg = f"fixture {fixture.id} contains a team outside the season"
            raise FeatureBuildError(msg)
        if fixture.status != FixtureStatus.FINISHED:
            msg = f"fixture {fixture.id} must be finished for historical features"
            raise FeatureBuildError(msg)
        if fixture.outcome is None or fixture.full_time_score is None:
            msg = f"fixture {fixture.id} is missing its training label"
            raise FeatureBuildError(msg)
        if not any(
            reference.source_id == provenance.source.source_id
            for reference in fixture.source_references
        ):
            msg = f"fixture {fixture.id} is not traceable to the declared source"
            raise FeatureBuildError(msg)


def build_point_in_time_feature_rows(
    fixtures: Sequence[Fixture],
    season: PremierLeagueSeason,
    provenance: CanonicalDatasetProvenance,
) -> tuple[PointInTimeFeatureRow, ...]:
    """Build deterministic within-season features, then update after each batch."""

    _validate_build_inputs(fixtures, season, provenance)
    state: dict[UUID, list[_TeamObservation]] = {
        team_id: [] for team_id in season.team_ids
    }
    rows: list[PointInTimeFeatureRow] = []
    season_prior_fixtures = 0

    for batch in chronological_fixture_batches(fixtures):
        for fixture in batch.fixtures:
            predictors = _predictors_for_fixture(
                fixture,
                state,
                season,
                season_prior_fixtures,
            )
            row_id = deterministic_feature_row_id(
                fixture_id=fixture.id,
                feature_cutoff_at=batch.feature_cutoff_at,
                predictor_schema_id=predictors.schema_id,
                predictor_schema_version=predictors.schema_version,
                canonical_dataset_id=provenance.dataset_id,
                canonical_fixtures_sha256=provenance.fixtures_sha256,
            )
            assert fixture.full_time_score is not None
            assert fixture.outcome is not None
            rows.append(
                PointInTimeFeatureRow(
                    id=row_id,
                    fixture_id=fixture.id,
                    competition_id=fixture.competition_id,
                    season_id=fixture.season_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    kickoff_at=fixture.kickoff_at,
                    kickoff_precision=fixture.kickoff_precision,
                    feature_cutoff_at=batch.feature_cutoff_at,
                    predictors=predictors,
                    training_label=TrainingLabel(
                        outcome=fixture.outcome,
                        home_goals=fixture.full_time_score.home,
                        away_goals=fixture.full_time_score.away,
                    ),
                    provenance=provenance,
                )
            )

        for fixture in batch.fixtures:
            state[fixture.home_team_id].append(_observation(fixture, home=True))
            state[fixture.away_team_id].append(_observation(fixture, home=False))
        season_prior_fixtures += len(batch.fixtures)

    return tuple(rows)
