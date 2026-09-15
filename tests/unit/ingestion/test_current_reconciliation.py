"""Current completed-result and standings transformation tests."""

from datetime import timedelta

import pytest

from pl_platform.domain.current import (
    CompletedFixtureResult,
    CurrentSeasonTeam,
    ProviderFixtureIdentifier,
    ProviderTeamIdentifier,
    StandingRow,
)
from pl_platform.domain.fixtures import FixtureScore, MatchOutcome
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.ingestion.current import (
    CompletedResultsResponse,
    CurrentProviderCapability,
    CurrentSeasonTeamsResponse,
    StandingsResponse,
)
from pl_platform.ingestion.current_transform import (
    CurrentTeamResolution,
    CurrentTransformationError,
    reconcile_standings_with_results,
    transform_completed_results,
    transform_current_standings,
    transform_current_teams,
)
from tests.unit.ingestion.current_helpers import (
    NOW,
    SOURCE,
    capture_for,
    registry_and_season,
    scope,
)


def _resolution() -> tuple[CurrentTeamResolution, PremierLeagueSeason]:
    registry, season = registry_and_season()
    items = tuple(
        CurrentSeasonTeam(
            provider_team_id=ProviderTeamIdentifier(
                source_id=SOURCE, external_id=f"provider-{ordinal:02d}"
            ),
            provider_name=f"Provider Team {ordinal:02d}",
        )
        for ordinal in range(20)
    )
    response = CurrentSeasonTeamsResponse(
        scope=scope(),
        items=items,
        capture=capture_for(CurrentProviderCapability.TEAMS, 20),
    )
    return transform_current_teams(response, registry, season), season


def _result_response() -> CompletedResultsResponse:
    result = CompletedFixtureResult(
        provider_fixture_id=ProviderFixtureIdentifier(
            source_id=SOURCE, external_id="fixture-1"
        ),
        home_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE, external_id="provider-00"
        ),
        away_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE, external_id="provider-01"
        ),
        full_time_score=FixtureScore(home=2, away=1),
        outcome=MatchOutcome.HOME_WIN,
        completed_at=NOW - timedelta(minutes=1),
    )
    return CompletedResultsResponse(
        scope=scope(),
        items=(result,),
        capture=capture_for(CurrentProviderCapability.COMPLETED_RESULTS, 1),
    )


def _standings_response(*, wrong_played: bool = False) -> StandingsResponse:
    items: list[StandingRow] = []
    for ordinal in range(20):
        if ordinal == 0:
            values = (0 if wrong_played else 1, 1, 0, 0, 2, 1, 1, 3)
        elif ordinal == 1:
            values = (1, 0, 0, 1, 1, 2, -1, 0)
        else:
            values = (0, 0, 0, 0, 0, 0, 0, 0)
        played, won, drawn, lost, goals_for, goals_against, difference, points = values
        items.append(
            StandingRow(
                provider_team_id=ProviderTeamIdentifier(
                    source_id=SOURCE, external_id=f"provider-{ordinal:02d}"
                ),
                position=ordinal + 1,
                played=played,
                won=won,
                drawn=drawn,
                lost=lost,
                goals_for=goals_for,
                goals_against=goals_against,
                goal_difference=difference,
                points=points,
            )
        )
    return StandingsResponse(
        scope=scope(),
        items=tuple(items),
        capture=capture_for(
            CurrentProviderCapability.STANDINGS,
            20,
            retrieved_at=NOW + timedelta(minutes=1),
        ),
    )


def test_completed_results_resolve_to_stable_canonical_fixture() -> None:
    resolution, season = _resolution()

    (result,) = transform_completed_results(_result_response(), resolution, season)

    assert result.home_team_id == resolution.by_provider_id["provider-00"].id
    assert result.away_team_id == resolution.by_provider_id["provider-01"].id
    assert result.capture.retrieved_at == NOW


def test_complete_standings_reconcile_at_retrieval_time() -> None:
    resolution, season = _resolution()
    results = transform_completed_results(_result_response(), resolution, season)
    snapshot = transform_current_standings(_standings_response(), resolution, season)

    reconcile_standings_with_results(snapshot, results)

    assert len(snapshot.rows) == 20
    assert snapshot.rows[0].team_id == resolution.by_provider_id["provider-00"].id


def test_standings_fail_closed_on_arithmetic_or_incomplete_membership() -> None:
    resolution, season = _resolution()
    results = transform_completed_results(_result_response(), resolution, season)
    with pytest.raises(ValueError, match="played count"):
        _standings_response(wrong_played=True)

    response = _standings_response()
    incomplete = response.model_copy(
        update={
            "items": response.items[:-1],
            "capture": capture_for(CurrentProviderCapability.STANDINGS, 19),
        }
    )
    with pytest.raises(CurrentTransformationError, match="complete reviewed"):
        transform_current_standings(incomplete, resolution, season)

    snapshot = transform_current_standings(response, resolution, season)
    bad_result = results[0].__class__(
        fixture_id=results[0].fixture_id,
        competition_id=results[0].competition_id,
        season_id=results[0].season_id,
        home_team_id=results[0].home_team_id,
        away_team_id=results[0].away_team_id,
        observation=results[0].observation.model_copy(
            update={"full_time_score": FixtureScore(home=3, away=1)}
        ),
        capture=results[0].capture,
    )
    with pytest.raises(CurrentTransformationError, match="do not reconcile"):
        reconcile_standings_with_results(snapshot, (bad_result,))
