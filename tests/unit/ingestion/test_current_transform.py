"""Pure current-season team and fixture transformation tests."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from pl_platform.domain.current import (
    CurrentSeasonFixture,
    CurrentSeasonTeam,
    ProviderFixtureIdentifier,
    ProviderKickoff,
    ProviderTeamIdentifier,
)
from pl_platform.domain.fixtures import FixtureStatus, KickoffPrecision
from pl_platform.domain.teams import UnknownTeamAliasError
from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentSeasonFixturesResponse,
    CurrentSeasonTeamsResponse,
)
from pl_platform.ingestion.current_transform import (
    CurrentTransformationError,
    current_fixture_batches,
    transform_current_fixtures,
    transform_current_teams,
)
from tests.unit.ingestion.current_helpers import (
    NOW,
    SOURCE,
    capture_for,
    registry_and_season,
    scope,
)


def _team_observation(
    ordinal: int, *, external_id: str | None = None
) -> CurrentSeasonTeam:
    return CurrentSeasonTeam(
        provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=external_id or f"provider-{ordinal:02d}",
        ),
        provider_name=f"Provider Team {ordinal:02d}",
    )


def _teams_response(*ordinals: int) -> CurrentSeasonTeamsResponse:
    items = tuple(
        sorted(
            (_team_observation(ordinal) for ordinal in ordinals),
            key=lambda item: item.provider_team_id.external_id,
        )
    )
    return CurrentSeasonTeamsResponse(
        scope=scope(),
        items=items,
        capture=capture_for(CurrentProviderCapability.TEAMS, len(items)),
    )


def _fixture(
    external_id: str,
    home: int,
    away: int,
    kickoff_at: datetime,
    *,
    precision: KickoffPrecision = KickoffPrecision.EXACT,
    status: FixtureStatus = FixtureStatus.SCHEDULED,
    timezone_name: str = "Europe/London",
) -> CurrentSeasonFixture:
    return CurrentSeasonFixture(
        provider_fixture_id=ProviderFixtureIdentifier(
            source_id=SOURCE,
            external_id=external_id,
        ),
        home_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=f"provider-{home:02d}",
        ),
        away_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id=f"provider-{away:02d}",
        ),
        kickoff=ProviderKickoff(
            kickoff_at=kickoff_at,
            precision=precision,
            source_timezone=timezone_name,
            source_local_date=kickoff_at.astimezone(ZoneInfo(timezone_name)).date(),
        ),
        status=status,
        matchweek=1,
        venue="Provider Ground",
        provider_updated_at=NOW,
    )


def _fixture_response(
    items: tuple[CurrentSeasonFixture, ...],
) -> CurrentSeasonFixturesResponse:
    return CurrentSeasonFixturesResponse(
        scope=scope(),
        items=tuple(
            sorted(
                items,
                key=lambda item: (
                    item.kickoff.kickoff_at,
                    item.provider_fixture_id.external_id,
                ),
            )
        ),
        capture=capture_for(CurrentProviderCapability.FIXTURES, len(items)),
    )


def test_resolves_reviewed_external_ids_and_aliases_without_fuzzy_matching() -> None:
    registry, season = registry_and_season()
    response = _teams_response(0, 1)

    resolution = transform_current_teams(response, registry, season)

    assert tuple(resolution.by_provider_id) == ("provider-00", "provider-01")
    assert resolution.teams[0].capture.response.body == b'{"ok":true}\n'

    alias_only = CurrentSeasonTeamsResponse(
        scope=scope(),
        items=(_team_observation(0, external_id="unmapped-id"),),
        capture=capture_for(CurrentProviderCapability.TEAMS, 1),
    )
    assert (
        transform_current_teams(alias_only, registry, season).teams[0].canonical_team
        == resolution.teams[0].canonical_team
    )

    unknown = CurrentSeasonTeamsResponse(
        scope=scope(),
        items=(
            CurrentSeasonTeam(
                provider_team_id=ProviderTeamIdentifier(
                    source_id=SOURCE,
                    external_id="unknown",
                ),
                provider_name="Almost Team 00",
            ),
        ),
        capture=capture_for(CurrentProviderCapability.TEAMS, 1),
    )
    with pytest.raises(UnknownTeamAliasError, match="unknown provider team"):
        transform_current_teams(unknown, registry, season)


def test_fixture_transform_preserves_stable_identity_status_and_provenance() -> None:
    registry, season = registry_and_season()
    resolution = transform_current_teams(_teams_response(0, 1), registry, season)
    scheduled = _fixture(
        "fixture-1",
        0,
        1,
        datetime(2026, 9, 20, 14, tzinfo=UTC),
    )
    transformed = transform_current_fixtures(
        _fixture_response((scheduled,)),
        resolution,
        season,
    )[0]
    postponed = _fixture(
        "fixture-1",
        0,
        1,
        datetime(2026, 10, 20, 14, tzinfo=UTC),
        status=FixtureStatus.POSTPONED,
    )
    changed = transform_current_fixtures(
        _fixture_response((postponed,)),
        resolution,
        season,
    )[0]

    assert transformed.fixture.id == changed.fixture.id
    assert changed.fixture.status is FixtureStatus.POSTPONED
    assert transformed.fixture.source_references[0].external_id == "fixture-1"
    assert transformed.observation.venue == "Provider Ground"
    assert transformed.capture.request_identity.sha256
    assert transformed.fixture.full_time_score is None


def test_fixture_transform_fails_on_unresolved_or_finished_observations() -> None:
    registry, season = registry_and_season()
    resolution = transform_current_teams(_teams_response(0), registry, season)
    unresolved = _fixture(
        "fixture-1",
        0,
        1,
        datetime(2026, 9, 20, 14, tzinfo=UTC),
    )
    with pytest.raises(CurrentTransformationError, match="unresolved"):
        transform_current_fixtures(
            _fixture_response((unresolved,)),
            resolution,
            season,
        )

    complete = _fixture(
        "fixture-2",
        0,
        1,
        datetime(2026, 9, 21, 14, tzinfo=UTC),
        status=FixtureStatus.FINISHED,
    )
    complete_resolution = transform_current_teams(
        _teams_response(0, 1), registry, season
    )
    with pytest.raises(CurrentTransformationError, match="result reconciliation"):
        transform_current_fixtures(
            _fixture_response((complete,)),
            complete_resolution,
            season,
        )
    outside_season = _fixture(
        "fixture-3",
        0,
        1,
        datetime(2027, 6, 1, 14, tzinfo=UTC),
    )
    with pytest.raises(CurrentTransformationError, match="outside"):
        transform_current_fixtures(
            _fixture_response((outside_season,)),
            complete_resolution,
            season,
        )


def test_date_only_fixture_absorbs_same_local_date_exact_fixtures() -> None:
    registry, season = registry_and_season()
    resolution = transform_current_teams(_teams_response(0, 1, 2), registry, season)
    date_only = _fixture(
        "fixture-a",
        0,
        1,
        datetime(2026, 9, 20, 11, tzinfo=UTC),
        precision=KickoffPrecision.DATE_ONLY,
    )
    exact = _fixture(
        "fixture-b",
        1,
        2,
        datetime(2026, 9, 20, 15, tzinfo=UTC),
    )
    later = _fixture(
        "fixture-c",
        2,
        0,
        datetime(2026, 9, 21, 15, tzinfo=UTC),
    )
    transformed = transform_current_fixtures(
        _fixture_response((date_only, exact, later)),
        resolution,
        season,
    )

    batches = current_fixture_batches(transformed)

    assert len(batches) == 2
    assert batches[0].is_date_only_batch
    assert len(batches[0].fixtures) == 2
    assert batches[0].knowledge_available_at == NOW
    assert batches[0].feature_cutoff_at == datetime(
        2026, 9, 19, 22, 59, 59, 999999, tzinfo=UTC
    )
    assert not batches[1].is_date_only_batch


def test_transformation_rejects_scope_duplicates_and_mixed_timezones() -> None:
    registry, season = registry_and_season()
    mismatched_scope = scope().model_copy(update={"season_id": "2025-2026"})
    response = CurrentSeasonTeamsResponse(
        scope=mismatched_scope,
        items=(),
        capture=capture_for(CurrentProviderCapability.TEAMS, 0),
    )
    with pytest.raises(CurrentTransformationError, match="canonical season"):
        transform_current_teams(response, registry, season)

    resolution = transform_current_teams(_teams_response(0, 1, 2), registry, season)
    first = transform_current_fixtures(
        _fixture_response(
            (
                _fixture(
                    "fixture-a",
                    0,
                    1,
                    datetime(2026, 9, 20, 15, tzinfo=UTC),
                ),
                _fixture(
                    "fixture-b",
                    1,
                    2,
                    datetime(2026, 9, 21, 15, tzinfo=UTC),
                    timezone_name="UTC",
                ),
            )
        ),
        resolution,
        season,
    )
    with pytest.raises(CurrentTransformationError, match="one source timezone"):
        current_fixture_batches(first)
    with pytest.raises(CurrentTransformationError, match="more than once"):
        current_fixture_batches((first[0], first[0]))
