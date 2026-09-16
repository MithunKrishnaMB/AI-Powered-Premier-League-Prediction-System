"""Composable current-data jobs with injected persistence dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pl_platform.automation.polling import FixturePollingPlan, KickoffAwarePollingPolicy
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.ingestion.current import CurrentSeasonFixturesRequest
from pl_platform.ingestion.current_transform import (
    CanonicalCurrentFixture,
    CurrentTeamResolution,
)
from pl_platform.ingestion.live_fixtures import (
    CacheAwareLiveFixtureReader,
    LiveFixtureReadResult,
)
from pl_platform.persistence.repositories import PersistenceResult


class CurrentFixtureSyncRepository(Protocol):
    def synchronize_fixtures(
        self,
        fixtures: tuple[CanonicalCurrentFixture, ...],
    ) -> PersistenceResult: ...


@dataclass(frozen=True, slots=True)
class FixturePollingJobResult:
    read: LiveFixtureReadResult
    polling: FixturePollingPlan
    persistence: PersistenceResult | None


class FixturePollingJob:
    """Read, persist, then plan the next fixture poll without scheduling it."""

    def __init__(
        self,
        *,
        reader: CacheAwareLiveFixtureReader,
        repository: CurrentFixtureSyncRepository,
        policy: KickoffAwarePollingPolicy | None = None,
    ) -> None:
        self._reader = reader
        self._repository = repository
        self._policy = policy or KickoffAwarePollingPolicy()

    def run(
        self,
        request: CurrentSeasonFixturesRequest,
        *,
        resolution: CurrentTeamResolution,
        season: PremierLeagueSeason,
        at: datetime,
    ) -> FixturePollingJobResult:
        read = self._reader.read(request, resolution=resolution, season=season, at=at)
        persistence = (
            self._repository.synchronize_fixtures(read.fixtures)
            if read.fixtures
            else None
        )
        return FixturePollingJobResult(
            read=read,
            polling=self._policy.plan(read.fixtures, at=at),
            persistence=persistence,
        )
