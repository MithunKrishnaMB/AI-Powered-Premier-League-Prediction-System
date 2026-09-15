"""Raw-manifest-gated persistence for current player and squad snapshots."""

import hashlib
import json
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    ProviderResponseCapture,
    deterministic_provider_cache_key,
)
from pl_platform.ingestion.current_squads import (
    CanonicalSquadSnapshot,
    CurrentPlayerResolution,
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


def _identity_object(value: Mapping[str, object]) -> StoredObject:
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
        format_id="current-squad-snapshot-v1",
        canonicalization_profile=CanonicalizationProfile.IDENTITY_JSON,
    )


def _cache_key(capture: ProviderResponseCapture) -> str:
    return deterministic_provider_cache_key(
        source_id=capture.source_id,
        capability=capture.capability,
        request_identity_sha256=capture.request_identity.sha256,
        fetched_at=capture.retrieved_at,
    )


def current_players_sync_plan(
    resolution: CurrentPlayerResolution,
) -> AggregateWritePlan:
    """Persist reviewed player mappings and exact-response observations."""

    if not resolution.players:
        raise RepositoryContractError("player synchronization cannot be empty")
    if any(
        item.capture.capability is not CurrentProviderCapability.PLAYERS
        for item in resolution.players
    ):
        raise RepositoryContractError("player synchronization requires player captures")
    player_rows: list[ImmutableRow] = []
    reference_rows: list[ImmutableRow] = []
    observation_rows: list[ImmutableRow] = []
    for item in resolution.players:
        player = item.canonical_player
        observation = item.observation
        cache_key = _cache_key(item.capture)
        observation_id = uuid5(
            NAMESPACE_URL,
            f"pl-platform:current-player-observation:1|{player.id}|{cache_key}",
        )
        player_rows.append(
            ImmutableRow.build(
                PersistenceTable.PLAYER,
                {"player_id": player.id},
                identity_columns=("player_id",),
            )
        )
        reference_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_PLAYER_SOURCE_REFERENCE,
                {
                    "source_id": observation.provider_player_id.source_id,
                    "external_id": observation.provider_player_id.external_id,
                    "player_id": player.id,
                },
                identity_columns=("source_id", "external_id"),
            )
        )
        observation_rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_PLAYER_OBSERVATION,
                {
                    "observation_id": observation_id,
                    "player_id": player.id,
                    "source_id": observation.provider_player_id.source_id,
                    "external_id": observation.provider_player_id.external_id,
                    "cache_key_sha256": cache_key,
                    "provider_name": observation.provider_name,
                    "date_of_birth": observation.date_of_birth,
                    "nationality_code": observation.nationality_code,
                    "provider_position": observation.provider_position,
                    "retrieved_at": item.capture.retrieved_at,
                },
                identity_columns=("observation_id",),
            )
        )
    aggregate_hash = hashlib.sha256(
        "".join(str(item.canonical_player.id) for item in resolution.players).encode()
    ).hexdigest()
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_PLAYERS,
        identity=(
            f"{resolution.competition_id}|{resolution.season_id}|{aggregate_hash}"
        ),
        rows=tuple(player_rows + reference_rows + observation_rows),
    )


def current_squad_sync_plan(
    snapshot: CanonicalSquadSnapshot,
) -> AggregateWritePlan:
    """Persist one complete, content-derived 20-team squad snapshot."""

    if any(
        squad.capture.capability is not CurrentProviderCapability.SQUADS
        for squad in snapshot.squads
    ):
        raise RepositoryContractError("squad synchronization requires squad captures")
    provenance = tuple(sorted({_cache_key(item.capture) for item in snapshot.squads}))
    knowledge_at = max(item.capture.retrieved_at for item in snapshot.squads)
    identity = _identity_object(
        {
            "as_of_date": snapshot.as_of_date.isoformat(),
            "competition_id": snapshot.competition_id,
            "provenance": list(provenance),
            "schema_version": 1,
            "season_id": snapshot.season_id,
            "source_id": snapshot.source_id,
            "squads": [
                {
                    "memberships": [
                        {
                            "effective_from": membership.effective_from.isoformat(),
                            "effective_to": (
                                None
                                if membership.effective_to is None
                                else membership.effective_to.isoformat()
                            ),
                            "kind": membership.kind,
                            "loan_parent_team_id": (
                                None
                                if membership.loan_parent_team_id is None
                                else str(membership.loan_parent_team_id)
                            ),
                            "player_id": str(membership.player_id),
                            "registered_from": (membership.registered_from.isoformat()),
                            "registered_to": (
                                None
                                if membership.registered_to is None
                                else membership.registered_to.isoformat()
                            ),
                            "shirt_number": membership.shirt_number,
                        }
                        for membership in squad.memberships
                    ],
                    "squad_id": str(squad.squad_id),
                    "team_id": str(squad.team_id),
                }
                for squad in snapshot.squads
            ],
        }
    )
    snapshot_id = uuid5(
        NAMESPACE_URL,
        f"pl-platform:current-squad-snapshot:1|{identity.sha256}",
    )
    squad_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_SQUAD,
            {
                "squad_id": squad.squad_id,
                "competition_id": squad.competition_id,
                "season_id": squad.season_id,
                "team_id": squad.team_id,
            },
            identity_columns=("squad_id",),
        )
        for squad in snapshot.squads
    ]
    reference_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_SQUAD_SOURCE_REFERENCE,
            {
                "source_id": squad.observation.provider_squad_id.source_id,
                "external_id": squad.observation.provider_squad_id.external_id,
                "squad_id": squad.squad_id,
            },
            identity_columns=("source_id", "external_id"),
        )
        for squad in snapshot.squads
    ]
    snapshot_row = ImmutableRow.build(
        PersistenceTable.CURRENT_SQUAD_SNAPSHOT,
        {
            "snapshot_id": snapshot_id,
            "identity_sha256": identity.sha256,
            "competition_id": snapshot.competition_id,
            "season_id": snapshot.season_id,
            "source_id": snapshot.source_id,
            "as_of_date": snapshot.as_of_date,
            "knowledge_available_at": knowledge_at,
        },
        identity_columns=("snapshot_id",),
    )
    provenance_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_SQUAD_SNAPSHOT_PROVENANCE,
            {"snapshot_id": snapshot_id, "cache_key_sha256": cache_key},
            identity_columns=("snapshot_id", "cache_key_sha256"),
        )
        for cache_key in provenance
    ]
    snapshot_team_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_SQUAD_SNAPSHOT_TEAM,
            {
                "snapshot_id": snapshot_id,
                "ordinal": ordinal,
                "squad_id": squad.squad_id,
                "team_id": squad.team_id,
            },
            identity_columns=("snapshot_id", "ordinal"),
        )
        for ordinal, squad in enumerate(snapshot.squads)
    ]
    member_rows = [
        ImmutableRow.build(
            PersistenceTable.CURRENT_SQUAD_MEMBER,
            {
                "snapshot_id": snapshot_id,
                "squad_id": squad.squad_id,
                "team_id": squad.team_id,
                "player_id": membership.player_id,
                "source_id": membership.provider_player_id.source_id,
                "external_id": membership.provider_player_id.external_id,
                "membership_kind": membership.kind,
                "effective_from": membership.effective_from,
                "effective_to": membership.effective_to,
                "registered_from": membership.registered_from,
                "registered_to": membership.registered_to,
                "loan_parent_team_id": membership.loan_parent_team_id,
                "shirt_number": membership.shirt_number,
            },
            identity_columns=("snapshot_id", "squad_id", "player_id"),
        )
        for squad in snapshot.squads
        for membership in squad.memberships
    ]
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_SQUADS,
        identity=str(snapshot_id),
        objects=(identity,),
        rows=tuple(
            squad_rows
            + reference_rows
            + [snapshot_row]
            + provenance_rows
            + snapshot_team_rows
            + member_rows
        ),
    )


class CurrentSquadRepository:
    """Narrow player/squad façade over the common immutable writer."""

    def __init__(self, repository: PostgresAggregateRepository) -> None:
        self._repository = repository

    def synchronize_players(
        self, resolution: CurrentPlayerResolution
    ) -> PersistenceResult:
        return self._repository.persist(current_players_sync_plan(resolution))

    def synchronize_squads(self, snapshot: CanonicalSquadSnapshot) -> PersistenceResult:
        return self._repository.persist(current_squad_sync_plan(snapshot))
