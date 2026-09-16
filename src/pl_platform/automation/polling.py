"""Pure kickoff-aware polling policy for canonical current fixtures."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from pl_platform.domain.fixtures import FixtureStatus, KickoffPrecision
from pl_platform.ingestion.current_transform import CanonicalCurrentFixture


class FixturePollReason(StrEnum):
    """Stable explanation for one deterministic polling decision."""

    IN_PROGRESS = "in_progress"
    OVERDUE_EXACT_KICKOFF = "overdue_exact_kickoff"
    IMMINENT_EXACT_KICKOFF = "imminent_exact_kickoff"
    NEAR_EXACT_KICKOFF = "near_exact_kickoff"
    DISTANT_EXACT_KICKOFF = "distant_exact_kickoff"
    DATE_ONLY_UPCOMING = "date_only_upcoming"
    DATE_ONLY_ACTIVE_DAY = "date_only_active_day"
    DATE_ONLY_OVERDUE = "date_only_overdue"
    POSTPONED = "postponed"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class FixturePollDecision:
    fixture_id: UUID
    reason: FixturePollReason
    next_poll_at: datetime | None


@dataclass(frozen=True, slots=True)
class FixturePollingPlan:
    evaluated_at: datetime
    decisions: tuple[FixturePollDecision, ...]
    next_poll_at: datetime | None


class KickoffAwarePollingPolicy:
    """Compute polling times without performing I/O or scheduling work."""

    def plan(
        self,
        fixtures: Sequence[CanonicalCurrentFixture],
        *,
        at: datetime,
    ) -> FixturePollingPlan:
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("polling evaluation time must be timezone-aware UTC")
        identities = tuple(item.fixture.id for item in fixtures)
        if len(identities) != len(set(identities)):
            raise ValueError("polling input repeats a canonical fixture identity")

        decisions = tuple(
            sorted(
                (self._decision(item, at=at) for item in fixtures),
                key=lambda item: item.fixture_id,
            )
        )
        pending = tuple(
            decision.next_poll_at
            for decision in decisions
            if decision.next_poll_at is not None
        )
        return FixturePollingPlan(
            evaluated_at=at,
            decisions=decisions,
            next_poll_at=min(pending) if pending else None,
        )

    @staticmethod
    def _decision(
        current: CanonicalCurrentFixture,
        *,
        at: datetime,
    ) -> FixturePollDecision:
        fixture = current.fixture
        if fixture.status in {FixtureStatus.CANCELLED, FixtureStatus.ABANDONED}:
            return FixturePollDecision(fixture.id, FixturePollReason.TERMINAL, None)
        if fixture.status is FixtureStatus.IN_PROGRESS:
            return FixturePollDecision(
                fixture.id,
                FixturePollReason.IN_PROGRESS,
                at + timedelta(minutes=1),
            )
        if fixture.status is FixtureStatus.POSTPONED:
            return FixturePollDecision(
                fixture.id,
                FixturePollReason.POSTPONED,
                at + timedelta(hours=6),
            )
        if fixture.status is FixtureStatus.FINISHED:
            return FixturePollDecision(fixture.id, FixturePollReason.TERMINAL, None)
        if fixture.kickoff_precision is KickoffPrecision.DATE_ONLY:
            return KickoffAwarePollingPolicy._date_only_decision(current, at=at)

        until_kickoff = fixture.kickoff_at - at
        if until_kickoff <= timedelta(0):
            reason = FixturePollReason.OVERDUE_EXACT_KICKOFF
            next_poll_at = at + timedelta(minutes=5)
        elif until_kickoff <= timedelta(hours=6):
            reason = FixturePollReason.IMMINENT_EXACT_KICKOFF
            next_poll_at = min(fixture.kickoff_at, at + timedelta(minutes=15))
        elif until_kickoff <= timedelta(days=2):
            reason = FixturePollReason.NEAR_EXACT_KICKOFF
            next_poll_at = at + timedelta(hours=1)
        elif until_kickoff <= timedelta(days=7):
            reason = FixturePollReason.DISTANT_EXACT_KICKOFF
            next_poll_at = at + timedelta(hours=6)
        else:
            reason = FixturePollReason.DISTANT_EXACT_KICKOFF
            next_poll_at = at + timedelta(days=1)
        return FixturePollDecision(fixture.id, reason, next_poll_at)

    @staticmethod
    def _date_only_decision(
        current: CanonicalCurrentFixture,
        *,
        at: datetime,
    ) -> FixturePollDecision:
        timezone = ZoneInfo(current.source_timezone)
        local_start = datetime.combine(
            current.source_local_date,
            time.min,
            tzinfo=timezone,
        ).astimezone(UTC)
        local_end = local_start + timedelta(days=1)
        if at < local_start:
            return FixturePollDecision(
                current.fixture.id,
                FixturePollReason.DATE_ONLY_UPCOMING,
                min(local_start, at + timedelta(days=1)),
            )
        if at < local_end:
            return FixturePollDecision(
                current.fixture.id,
                FixturePollReason.DATE_ONLY_ACTIVE_DAY,
                at + timedelta(hours=1),
            )
        return FixturePollDecision(
            current.fixture.id,
            FixturePollReason.DATE_ONLY_OVERDUE,
            at + timedelta(hours=6),
        )
