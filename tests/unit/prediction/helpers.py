"""Synthetic current-season evidence for lifecycle tests."""

from datetime import UTC, datetime
from uuid import UUID

from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatus,
    KickoffPrecision,
    SourceFixtureReference,
)
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.features.elo import initialize_season_ratings
from pl_platform.features.priors import SeasonOpeningPrior, build_season_opening_priors
from pl_platform.prediction.domain import (
    CompletedResultEvidence,
    CurrentFixtureEvidence,
)
from tests.unit.ingestion.current_helpers import SOURCE, registry_and_season


def feature_inputs() -> tuple[
    CurrentFixtureEvidence,
    CompletedResultEvidence,
    PremierLeagueSeason,
    dict[UUID, SeasonOpeningPrior],
    dict[UUID, float],
]:
    _, season = registry_and_season()
    teams = tuple(sorted(season.team_ids))
    completed_score = FixtureScore(home=2, away=1)
    completed_fixture = Fixture(
        id=UUID(int=1001),
        competition_id=season.competition_id,
        season_id=season.id,
        kickoff_at=datetime(2026, 8, 15, 14, tzinfo=UTC),
        home_team_id=teams[0],
        away_team_id=teams[1],
        status=FixtureStatus.FINISHED,
        full_time_score=completed_score,
        outcome=completed_score.outcome,
        source_references=(
            SourceFixtureReference(source_id=SOURCE, external_id="completed-1"),
        ),
    )
    completed = CompletedResultEvidence(
        fixture=completed_fixture,
        result_id=UUID(int=2001),
        result_identity_sha256="1" * 64,
        observation_id=UUID(int=3001),
        cache_key_sha256="2" * 64,
        retrieved_at=datetime(2026, 8, 15, 17, tzinfo=UTC),
    )
    upcoming_fixture = Fixture(
        id=UUID(int=1002),
        competition_id=season.competition_id,
        season_id=season.id,
        kickoff_at=datetime(2026, 9, 20, 14, tzinfo=UTC),
        kickoff_precision=KickoffPrecision.EXACT,
        home_team_id=teams[0],
        away_team_id=teams[2],
        status=FixtureStatus.SCHEDULED,
        source_references=(
            SourceFixtureReference(source_id=SOURCE, external_id="upcoming-1"),
        ),
    )
    upcoming = CurrentFixtureEvidence(
        fixture=upcoming_fixture,
        revision_id=UUID(int=4001),
        revision_identity_sha256="3" * 64,
        observation_id=UUID(int=5001),
        cache_key_sha256="4" * 64,
        retrieved_at=datetime(2026, 9, 15, 8, tzinfo=UTC),
        batch_id=UUID(int=6001),
        batch_identity_sha256="5" * 64,
        batch_kind="exact_kickoff",
        batch_member_ordinal=0,
        knowledge_available_at=datetime(2026, 9, 15, 8, tzinfo=UTC),
    )
    priors = build_season_opening_priors(season)
    ratings = initialize_season_ratings(season)
    return upcoming, completed, season, priors, ratings
