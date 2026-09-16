"""Kickoff-aware polling policy and fixture job tests."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from pl_platform.automation.jobs import FixturePollingJob
from pl_platform.automation.polling import FixturePollReason, KickoffAwarePollingPolicy
from pl_platform.domain.current import (
    CurrentSeasonFixture,
    ProviderFixtureIdentifier,
    ProviderKickoff,
    ProviderTeamIdentifier,
)
from pl_platform.domain.fixtures import FixtureStatus, KickoffPrecision
from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentSeasonFixturesRequest,
)
from pl_platform.ingestion.current_transform import (
    CanonicalCurrentFixture,
    transform_current_fixtures,
)
from pl_platform.ingestion.live_fixtures import (
    CacheAwareLiveFixtureReader,
    LiveFixtureReadResult,
)
from pl_platform.persistence.repositories import AggregateKind, PersistenceResult
from tests.unit.ingestion.current_helpers import NOW, SOURCE, request_for
from tests.unit.ingestion.test_current_reconciliation import _resolution
from tests.unit.ingestion.test_current_transform import _fixture_response


def _current(
    *,
    status: FixtureStatus = FixtureStatus.SCHEDULED,
    kickoff_at: datetime = NOW + timedelta(days=3),
    precision: KickoffPrecision = KickoffPrecision.EXACT,
    local_date: date | None = None,
) -> CanonicalCurrentFixture:
    resolution, season = _resolution()
    observation = CurrentSeasonFixture(
        provider_fixture_id=ProviderFixtureIdentifier(
            source_id=SOURCE,
            external_id="fixture-1",
        ),
        home_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id="provider-00",
        ),
        away_provider_team_id=ProviderTeamIdentifier(
            source_id=SOURCE,
            external_id="provider-01",
        ),
        kickoff=ProviderKickoff(
            kickoff_at=kickoff_at,
            precision=precision,
            source_timezone="Europe/London",
            source_local_date=local_date or kickoff_at.date(),
        ),
        status=status,
        matchweek=5,
        provider_updated_at=NOW,
    )
    response = _fixture_response((observation,))
    return transform_current_fixtures(response, resolution, season)[0]


@pytest.mark.parametrize(
    ("status", "reason", "delay"),
    (
        (
            FixtureStatus.IN_PROGRESS,
            FixturePollReason.IN_PROGRESS,
            timedelta(minutes=1),
        ),
        (FixtureStatus.POSTPONED, FixturePollReason.POSTPONED, timedelta(hours=6)),
        (FixtureStatus.CANCELLED, FixturePollReason.TERMINAL, None),
        (FixtureStatus.ABANDONED, FixturePollReason.TERMINAL, None),
    ),
)
def test_status_specific_polling_is_deterministic(
    status: FixtureStatus,
    reason: FixturePollReason,
    delay: timedelta | None,
) -> None:
    decision = KickoffAwarePollingPolicy().plan((_current(status=status),), at=NOW)

    assert decision.decisions[0].reason is reason
    assert decision.next_poll_at == (NOW + delay if delay is not None else None)


@pytest.mark.parametrize(
    ("kickoff_delta", "reason", "poll_delta"),
    (
        (
            timedelta(minutes=-1),
            FixturePollReason.OVERDUE_EXACT_KICKOFF,
            timedelta(minutes=5),
        ),
        (
            timedelta(minutes=10),
            FixturePollReason.IMMINENT_EXACT_KICKOFF,
            timedelta(minutes=10),
        ),
        (
            timedelta(hours=4),
            FixturePollReason.IMMINENT_EXACT_KICKOFF,
            timedelta(minutes=15),
        ),
        (timedelta(hours=12), FixturePollReason.NEAR_EXACT_KICKOFF, timedelta(hours=1)),
        (
            timedelta(days=3),
            FixturePollReason.DISTANT_EXACT_KICKOFF,
            timedelta(hours=6),
        ),
        (timedelta(days=8), FixturePollReason.DISTANT_EXACT_KICKOFF, timedelta(days=1)),
    ),
)
def test_exact_kickoff_bands(
    kickoff_delta: timedelta,
    reason: FixturePollReason,
    poll_delta: timedelta,
) -> None:
    decision = KickoffAwarePollingPolicy().plan(
        (_current(kickoff_at=NOW + kickoff_delta),),
        at=NOW,
    )

    assert decision.decisions[0].reason is reason
    assert decision.next_poll_at == NOW + poll_delta


@pytest.mark.parametrize(
    ("at", "reason", "delay"),
    (
        (
            datetime(2026, 9, 18, 10, tzinfo=UTC),
            FixturePollReason.DATE_ONLY_UPCOMING,
            timedelta(days=1),
        ),
        (
            datetime(2026, 9, 20, 10, tzinfo=UTC),
            FixturePollReason.DATE_ONLY_ACTIVE_DAY,
            timedelta(hours=1),
        ),
        (
            datetime(2026, 9, 21, 10, tzinfo=UTC),
            FixturePollReason.DATE_ONLY_OVERDUE,
            timedelta(hours=6),
        ),
    ),
)
def test_date_only_policy_uses_provider_local_day(
    at: datetime,
    reason: FixturePollReason,
    delay: timedelta,
) -> None:
    current = _current(
        kickoff_at=datetime(2026, 9, 20, 11, tzinfo=UTC),
        precision=KickoffPrecision.DATE_ONLY,
        local_date=date(2026, 9, 20),
    )

    decision = KickoffAwarePollingPolicy().plan((current,), at=at)

    assert decision.decisions[0].reason is reason
    assert decision.next_poll_at == at + delay


def test_policy_rejects_non_utc_and_duplicate_inputs() -> None:
    policy = KickoffAwarePollingPolicy()
    current = _current()

    with pytest.raises(ValueError, match="UTC"):
        policy.plan((current,), at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="repeats"):
        policy.plan((current, current), at=NOW)


@dataclass
class _Reader:
    result: LiveFixtureReadResult

    def read(self, *args: object, **kwargs: object) -> LiveFixtureReadResult:
        return self.result


@dataclass
class _Repository:
    calls: list[tuple[CanonicalCurrentFixture, ...]] = field(default_factory=list)

    def synchronize_fixtures(
        self,
        fixtures: tuple[CanonicalCurrentFixture, ...],
    ) -> PersistenceResult:
        self.calls.append(fixtures)
        return PersistenceResult(
            AggregateKind.CURRENT_FIXTURES,
            "fixture-sync",
            "0" * 64,
            0,
            0,
            1,
            0,
        )


def test_fixture_job_persists_nonempty_reads_and_plans_next_poll() -> None:
    current = _current(kickoff_at=NOW + timedelta(minutes=5))
    reader = _Reader(LiveFixtureReadResult((current,), ()))
    repository = _Repository()
    resolution, season = _resolution()

    result = FixturePollingJob(
        reader=cast(CacheAwareLiveFixtureReader, reader),
        repository=repository,
    ).run(
        cast(
            CurrentSeasonFixturesRequest,
            request_for(CurrentProviderCapability.FIXTURES),
        ),
        resolution=resolution,
        season=season,
        at=NOW,
    )

    assert repository.calls == [(current,)]
    assert result.persistence is not None
    assert result.polling.next_poll_at == NOW + timedelta(minutes=5)


def test_fixture_job_does_not_persist_empty_reads() -> None:
    reader = _Reader(LiveFixtureReadResult((), ()))
    repository = _Repository()
    resolution, season = _resolution()

    result = FixturePollingJob(
        reader=cast(CacheAwareLiveFixtureReader, reader),
        repository=repository,
    ).run(
        cast(
            CurrentSeasonFixturesRequest,
            request_for(CurrentProviderCapability.FIXTURES),
        ),
        resolution=resolution,
        season=season,
        at=NOW,
    )

    assert repository.calls == []
    assert result.persistence is None
    assert result.polling.next_poll_at is None
