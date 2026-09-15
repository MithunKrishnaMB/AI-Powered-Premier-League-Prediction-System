"""Immutable current-season fixture, result and standings synchronization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    ProviderResponseCapture,
    deterministic_provider_cache_key,
)
from pl_platform.ingestion.current_transform import (
    CanonicalCompletedResult,
    CanonicalCurrentFixture,
    CanonicalStandingsSnapshot,
    current_fixture_batches,
    reconcile_standings_with_results,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    ImmutableRow,
    PersistenceResult,
    PersistenceTable,
    PostgresAggregateRepository,
    RepositoryContractError,
    StoredObject,
)

CURRENT_SYNC_SCHEMA_VERSION: Final = 1


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise RepositoryContractError("current synchronization time must be UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _identity_object(value: Mapping[str, object], *, format_id: str) -> StoredObject:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.IDENTITY_JSON,
    )


def _cache_key(capture: ProviderResponseCapture) -> str:
    return deterministic_provider_cache_key(
        source_id=capture.source_id,
        capability=capture.capability,
        request_identity_sha256=capture.request_identity.sha256,
        fetched_at=capture.retrieved_at,
    )


def _fixture_row(
    item: CanonicalCurrentFixture | CanonicalCompletedResult,
) -> ImmutableRow:
    fixture_id = (
        item.fixture.id
        if isinstance(item, CanonicalCurrentFixture)
        else item.fixture_id
    )
    return ImmutableRow.build(
        PersistenceTable.FIXTURE,
        {
            "fixture_id": fixture_id,
            "competition_id": item.competition_id
            if isinstance(item, CanonicalCompletedResult)
            else item.fixture.competition_id,
            "season_id": item.season_id
            if isinstance(item, CanonicalCompletedResult)
            else item.fixture.season_id,
            "home_team_id": item.home_team_id
            if isinstance(item, CanonicalCompletedResult)
            else item.fixture.home_team_id,
            "away_team_id": item.away_team_id
            if isinstance(item, CanonicalCompletedResult)
            else item.fixture.away_team_id,
        },
        identity_columns=("fixture_id",),
    )


def _source_reference_row(
    *, source_id: str, external_id: str, fixture_id: UUID
) -> ImmutableRow:
    return ImmutableRow.build(
        PersistenceTable.CURRENT_FIXTURE_SOURCE_REFERENCE,
        {
            "source_id": source_id,
            "external_id": external_id,
            "fixture_id": fixture_id,
        },
        identity_columns=("source_id", "external_id"),
    )


def current_fixture_sync_plan(
    fixtures: Sequence[CanonicalCurrentFixture],
) -> AggregateWritePlan:
    """Build one canonical, cache-provenanced fixture synchronization write."""

    if not fixtures:
        raise RepositoryContractError("fixture synchronization cannot be empty")
    identities = tuple(item.fixture.id for item in fixtures)
    if len(identities) != len(set(identities)):
        raise RepositoryContractError("fixture synchronization repeats an identity")
    scopes = {
        (item.fixture.competition_id, item.fixture.season_id) for item in fixtures
    }
    sources = {item.capture.source_id for item in fixtures}
    if len(scopes) != 1 or len(sources) != 1:
        raise RepositoryContractError("fixture synchronization must have one scope")
    if any(
        item.capture.capability
        not in {
            CurrentProviderCapability.FIXTURES,
            CurrentProviderCapability.FIXTURE_STATUS,
        }
        for item in fixtures
    ):
        raise RepositoryContractError(
            "fixture synchronization requires fixture or status captures"
        )

    ordered = tuple(sorted(fixtures, key=lambda item: item.fixture.id))
    objects: dict[str, StoredObject] = {}
    fixture_rows: list[ImmutableRow] = []
    reference_rows: list[ImmutableRow] = []
    revision_rows: list[ImmutableRow] = []
    observation_rows: list[ImmutableRow] = []
    revision_ids: dict[UUID, UUID] = {}

    for item in ordered:
        fixture = item.fixture
        observation = item.observation
        cache_key = _cache_key(item.capture)
        revision_identity = _identity_object(
            {
                "away_team_id": str(fixture.away_team_id),
                "competition_id": fixture.competition_id,
                "fixture_id": str(fixture.id),
                "home_team_id": str(fixture.home_team_id),
                "kickoff_at": _utc_text(fixture.kickoff_at),
                "kickoff_precision": fixture.kickoff_precision.value,
                "matchweek": fixture.matchweek,
                "referee": fixture.referee,
                "schema_version": CURRENT_SYNC_SCHEMA_VERSION,
                "season_id": fixture.season_id,
                "source_local_date": observation.kickoff.source_local_date.isoformat(),
                "source_timezone": observation.kickoff.source_timezone,
                "status": fixture.status.value,
                "venue": observation.venue,
            },
            format_id="current-fixture-revision-v1",
        )
        revision_id = uuid5(
            NAMESPACE_URL,
            f"pl-platform:current-fixture-revision:1|{revision_identity.sha256}",
        )
        revision_ids[fixture.id] = revision_id
        observation_id = uuid5(
            NAMESPACE_URL,
            "pl-platform:current-fixture-observation:1|"
            f"{fixture.id}|{cache_key}|{revision_id}",
        )
        objects[revision_identity.sha256] = revision_identity
        fixture_rows.append(_fixture_row(item))
        reference_rows.append(
            _source_reference_row(
                source_id=observation.provider_fixture_id.source_id,
                external_id=observation.provider_fixture_id.external_id,
                fixture_id=fixture.id,
            )
        )
        revision_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_FIXTURE_REVISION,
                {
                    "revision_id": revision_id,
                    "identity_sha256": revision_identity.sha256,
                    "fixture_id": fixture.id,
                    "competition_id": fixture.competition_id,
                    "season_id": fixture.season_id,
                    "home_team_id": fixture.home_team_id,
                    "away_team_id": fixture.away_team_id,
                    "kickoff_at": fixture.kickoff_at,
                    "kickoff_precision": fixture.kickoff_precision.value,
                    "source_timezone": observation.kickoff.source_timezone,
                    "source_local_date": observation.kickoff.source_local_date,
                    "status": fixture.status.value,
                    "matchweek": fixture.matchweek,
                    "venue": observation.venue,
                    "referee": fixture.referee,
                },
                identity_columns=("revision_id",),
            )
        )
        observation_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_FIXTURE_OBSERVATION,
                {
                    "observation_id": observation_id,
                    "fixture_id": fixture.id,
                    "revision_id": revision_id,
                    "source_id": observation.provider_fixture_id.source_id,
                    "external_id": observation.provider_fixture_id.external_id,
                    "cache_key_sha256": cache_key,
                    "provider_updated_at": observation.provider_updated_at,
                    "provider_observed_at": item.status_observed_at,
                    "retrieved_at": item.capture.retrieved_at,
                },
                identity_columns=("observation_id",),
            )
        )

    batch_rows: list[ImmutableRow] = []
    batch_provenance_rows: list[ImmutableRow] = []
    member_rows: list[ImmutableRow] = []
    batch_fixtures = tuple(
        item
        for item in fixtures
        if item.capture.capability is CurrentProviderCapability.FIXTURES
    )
    for batch in current_fixture_batches(batch_fixtures):
        provenance = tuple(
            sorted({_cache_key(item.capture) for item in batch.fixtures})
        )
        members = tuple(
            (item.fixture.id, revision_ids[item.fixture.id]) for item in batch.fixtures
        )
        exact_kickoff = None if batch.is_date_only_batch else batch.feature_cutoff_at
        batch_identity = _identity_object(
            {
                "competition_id": batch.fixtures[0].fixture.competition_id,
                "exact_kickoff_at": (
                    None if exact_kickoff is None else _utc_text(exact_kickoff)
                ),
                "kind": (
                    "date_only_date" if batch.is_date_only_batch else "exact_kickoff"
                ),
                "members": [str(fixture_id) for fixture_id, _ in members],
                "provenance": list(provenance),
                "schema_version": CURRENT_SYNC_SCHEMA_VERSION,
                "season_id": batch.fixtures[0].fixture.season_id,
                "source_local_date": batch.source_local_date.isoformat(),
                "source_timezone": batch.source_timezone,
            },
            format_id="current-fixture-batch-v1",
        )
        batch_id = uuid5(
            NAMESPACE_URL,
            f"pl-platform:current-fixture-batch:1|{batch_identity.sha256}",
        )
        objects[batch_identity.sha256] = batch_identity
        batch_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_FIXTURE_BATCH,
                {
                    "batch_id": batch_id,
                    "identity_sha256": batch_identity.sha256,
                    "competition_id": batch.fixtures[0].fixture.competition_id,
                    "season_id": batch.fixtures[0].fixture.season_id,
                    "batch_kind": (
                        "date_only_date"
                        if batch.is_date_only_batch
                        else "exact_kickoff"
                    ),
                    "source_timezone": batch.source_timezone,
                    "source_local_date": batch.source_local_date,
                    "exact_kickoff_at": exact_kickoff,
                    "feature_cutoff_at": batch.feature_cutoff_at,
                    "knowledge_available_at": batch.knowledge_available_at,
                },
                identity_columns=("batch_id",),
            )
        )
        batch_provenance_rows.extend(
            ImmutableRow.build(
                PersistenceTable.CURRENT_FIXTURE_BATCH_PROVENANCE,
                {"batch_id": batch_id, "cache_key_sha256": cache_key},
                identity_columns=("batch_id", "cache_key_sha256"),
            )
            for cache_key in provenance
        )
        member_rows.extend(
            ImmutableRow.build(
                PersistenceTable.CURRENT_FIXTURE_BATCH_MEMBER,
                {
                    "batch_id": batch_id,
                    "member_ordinal": ordinal,
                    "fixture_id": fixture_id,
                    "revision_id": revision_id,
                },
                identity_columns=("batch_id", "member_ordinal"),
            )
            for ordinal, (fixture_id, revision_id) in enumerate(members)
        )

    competition_id, season_id = next(iter(scopes))
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_FIXTURES,
        identity=f"{competition_id}|{season_id}|{hashlib.sha256(''.join(sorted(objects)).encode()).hexdigest()}",
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(
            fixture_rows
            + reference_rows
            + revision_rows
            + observation_rows
            + batch_rows
            + batch_provenance_rows
            + member_rows
        ),
    )


def current_results_sync_plan(
    results: Sequence[CanonicalCompletedResult],
) -> AggregateWritePlan:
    """Build an immutable official-result ledger update and its observations."""

    if not results:
        raise RepositoryContractError("result reconciliation cannot be empty")
    fixture_ids = tuple(item.fixture_id for item in results)
    if len(fixture_ids) != len(set(fixture_ids)):
        raise RepositoryContractError("result reconciliation repeats a fixture")
    if any(
        item.capture.capability is not CurrentProviderCapability.COMPLETED_RESULTS
        for item in results
    ):
        raise RepositoryContractError("result reconciliation requires result captures")
    ordered = tuple(sorted(results, key=lambda item: item.fixture_id))
    objects: list[StoredObject] = []
    fixture_rows: list[ImmutableRow] = []
    reference_rows: list[ImmutableRow] = []
    result_rows: list[ImmutableRow] = []
    observation_rows: list[ImmutableRow] = []
    for item in ordered:
        observation = item.observation
        cache_key = _cache_key(item.capture)
        identity = _identity_object(
            {
                "away_goals": observation.full_time_score.away,
                "fixture_id": str(item.fixture_id),
                "home_goals": observation.full_time_score.home,
                "outcome": observation.outcome.value,
                "schema_version": CURRENT_SYNC_SCHEMA_VERSION,
            },
            format_id="current-completed-result-v1",
        )
        result_id = uuid5(
            NAMESPACE_URL,
            f"pl-platform:current-completed-result:1|{identity.sha256}",
        )
        observation_id = uuid5(
            NAMESPACE_URL,
            f"pl-platform:current-result-observation:1|{result_id}|{cache_key}",
        )
        objects.append(identity)
        fixture_rows.append(_fixture_row(item))
        reference_rows.append(
            _source_reference_row(
                source_id=observation.provider_fixture_id.source_id,
                external_id=observation.provider_fixture_id.external_id,
                fixture_id=item.fixture_id,
            )
        )
        result_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_COMPLETED_RESULT,
                {
                    "result_id": result_id,
                    "identity_sha256": identity.sha256,
                    "fixture_id": item.fixture_id,
                    "competition_id": item.competition_id,
                    "season_id": item.season_id,
                    "home_team_id": item.home_team_id,
                    "away_team_id": item.away_team_id,
                    "full_time_home_goals": observation.full_time_score.home,
                    "full_time_away_goals": observation.full_time_score.away,
                    "outcome": observation.outcome.value,
                },
                identity_columns=("fixture_id",),
            )
        )
        observation_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_RESULT_OBSERVATION,
                {
                    "observation_id": observation_id,
                    "result_id": result_id,
                    "fixture_id": item.fixture_id,
                    "source_id": observation.provider_fixture_id.source_id,
                    "external_id": observation.provider_fixture_id.external_id,
                    "cache_key_sha256": cache_key,
                    "completed_at": observation.completed_at,
                    "retrieved_at": item.capture.retrieved_at,
                },
                identity_columns=("observation_id",),
            )
        )
    scope = {(item.competition_id, item.season_id) for item in ordered}
    if len(scope) != 1:
        raise RepositoryContractError("result reconciliation must have one scope")
    competition_id, season_id = next(iter(scope))
    aggregate_digest = hashlib.sha256(
        "".join(item.sha256 for item in objects).encode()
    ).hexdigest()
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_RESULTS,
        identity=f"{competition_id}|{season_id}|{aggregate_digest}",
        objects=tuple(objects),
        rows=tuple(fixture_rows + reference_rows + result_rows + observation_rows),
    )


def current_standings_sync_plan(
    snapshot: CanonicalStandingsSnapshot,
    completed_results: Sequence[CanonicalCompletedResult],
) -> AggregateWritePlan:
    """Build a full standings snapshot after point-in-time result reconciliation."""

    if snapshot.capture.capability is not CurrentProviderCapability.STANDINGS:
        raise RepositoryContractError(
            "standings synchronization requires standings capture"
        )
    reconcile_standings_with_results(snapshot, completed_results)
    cache_key = _cache_key(snapshot.capture)
    identity = _identity_object(
        {
            "cache_key_sha256": cache_key,
            "competition_id": snapshot.competition_id,
            "rows": [
                {
                    "drawn": row.observation.drawn,
                    "goal_difference": row.observation.goal_difference,
                    "goals_against": row.observation.goals_against,
                    "goals_for": row.observation.goals_for,
                    "lost": row.observation.lost,
                    "played": row.observation.played,
                    "points": row.observation.points,
                    "points_adjustment": row.observation.points_adjustment,
                    "position": row.observation.position,
                    "provider_team_id": row.observation.provider_team_id.external_id,
                    "team_id": str(row.team_id),
                    "won": row.observation.won,
                }
                for row in snapshot.rows
            ],
            "schema_version": CURRENT_SYNC_SCHEMA_VERSION,
            "season_id": snapshot.season_id,
        },
        format_id="current-standings-snapshot-v1",
    )
    snapshot_id = uuid5(
        NAMESPACE_URL,
        f"pl-platform:current-standings-snapshot:1|{identity.sha256}",
    )
    snapshot_row = ImmutableRow.build(
        PersistenceTable.CURRENT_STANDING_SNAPSHOT,
        {
            "snapshot_id": snapshot_id,
            "identity_sha256": identity.sha256,
            "competition_id": snapshot.competition_id,
            "season_id": snapshot.season_id,
            "source_id": snapshot.capture.source_id,
            "cache_key_sha256": cache_key,
            "retrieved_at": snapshot.capture.retrieved_at,
        },
        identity_columns=("snapshot_id",),
    )
    standing_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_STANDING_ROW,
            {
                "snapshot_id": snapshot_id,
                "team_id": row.team_id,
                "position": row.observation.position,
                "played": row.observation.played,
                "won": row.observation.won,
                "drawn": row.observation.drawn,
                "lost": row.observation.lost,
                "goals_for": row.observation.goals_for,
                "goals_against": row.observation.goals_against,
                "goal_difference": row.observation.goal_difference,
                "points": row.observation.points,
                "points_adjustment": row.observation.points_adjustment,
            },
            identity_columns=("snapshot_id", "team_id"),
        )
        for row in snapshot.rows
    ]
    reference_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_STANDING_SOURCE_REFERENCE,
            {
                "snapshot_id": snapshot_id,
                "team_id": row.team_id,
                "source_id": row.observation.provider_team_id.source_id,
                "external_id": row.observation.provider_team_id.external_id,
            },
            identity_columns=("snapshot_id", "team_id"),
        )
        for row in snapshot.rows
    ]
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_STANDINGS,
        identity=str(snapshot_id),
        objects=(identity,),
        rows=(snapshot_row, *standing_rows, *reference_rows),
    )


class CurrentSeasonRepository:
    """Narrow façade over the raw-manifest-gated aggregate repository."""

    def __init__(self, repository: PostgresAggregateRepository) -> None:
        self._repository = repository

    def synchronize_fixtures(
        self, fixtures: Sequence[CanonicalCurrentFixture]
    ) -> PersistenceResult:
        return self._repository.persist(current_fixture_sync_plan(fixtures))

    def reconcile_results(
        self, results: Sequence[CanonicalCompletedResult]
    ) -> PersistenceResult:
        return self._repository.persist(current_results_sync_plan(results))

    def synchronize_standings(
        self,
        snapshot: CanonicalStandingsSnapshot,
        completed_results: Sequence[CanonicalCompletedResult],
    ) -> PersistenceResult:
        return self._repository.persist(
            current_standings_sync_plan(snapshot, completed_results)
        )
