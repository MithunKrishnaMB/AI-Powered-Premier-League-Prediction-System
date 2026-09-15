"""Atomic write plans for append-only prediction lifecycle advancement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from pl_platform.domain.simulation import (
    FixtureScorelineDistribution,
    scoreline_distribution_identity_bytes,
    simulation_fixture_batches,
)
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.prediction.domain import (
    OperationalTeamState,
    PredictionRegeneration,
    TeamStateAdvancement,
    distribution_provenance_identity,
    prediction_regeneration_identity,
    season_simulation_regeneration_identity,
    team_state_advancement_identity,
    team_state_identity,
)
from pl_platform.prediction.lifecycle import initial_elo_bytes
from pl_platform.prediction.operations import SimulationRegenerationBundle
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.simulation.aggregate import simulation_summary_identity_bytes
from pl_platform.simulation.vectorized import (
    SIMULATION_ALGORITHM_VERSION,
    SIMULATION_COUNT,
    simulation_identity_bytes,
)

from .prediction import predictions_write_plan, upcoming_features_write_plan
from .repositories import (
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

_LONDON = ZoneInfo("Europe/London")


def _json_object(payload: bytes, format_id: str) -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
    )


def _identity_object(payload: bytes, format_id: str) -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.IDENTITY_JSON,
    )


def _state_objects_and_rows(
    state: OperationalTeamState,
) -> tuple[tuple[StoredObject, ...], tuple[ImmutableRow, ...]]:
    expected_id, expected_sha256, identity_bytes = team_state_identity(
        season_id=state.season_id,
        initial_elo_sha256=state.initial_elo_sha256,
        completed_results=state.completed_results,
        elo_ratings=state.elo_ratings,
    )
    if expected_id != state.id or expected_sha256 != state.identity_sha256:
        raise RepositoryContractError("operational team-state identity changed")
    identity_object = _json_object(identity_bytes, "operational-team-state-identity-v1")
    state_object = _json_object(
        canonical_json_bytes(state), "operational-team-state-v1"
    )
    rows: list[ImmutableRow] = [
        ImmutableRow.build(
            PersistenceTable.OPERATIONAL_TEAM_STATE,
            {
                "state_id": state.id,
                "identity_sha256": state.identity_sha256,
                "state_object_sha256": state_object.sha256,
                "schema_version": state.schema_version,
                "competition_id": "eng-premier-league",
                "season_id": state.season_id,
                "initial_elo_sha256": state.initial_elo_sha256,
                "completed_result_count": len(state.completed_results),
            },
            identity_columns=("state_id",),
        )
    ]
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.OPERATIONAL_TEAM_STATE_RESULT,
            {
                "state_id": state.id,
                "ordinal": ordinal,
                "result_id": item.result_id,
                "result_identity_sha256": item.result_identity_sha256,
                "result_observation_id": item.observation_id,
                "result_cache_key_sha256": item.cache_key_sha256,
                "result_retrieved_at": item.retrieved_at,
                "fixture_id": item.fixture.id,
            },
            identity_columns=("state_id", "ordinal"),
        )
        for ordinal, item in enumerate(state.completed_results)
    )
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.OPERATIONAL_TEAM_STATE_RATING,
            {
                "state_id": state.id,
                "team_id": item.team_id,
                "team_ordinal": ordinal,
                "elo_rating": item.rating,
            },
            identity_columns=("state_id", "team_id"),
        )
        for ordinal, item in enumerate(state.elo_ratings)
    )
    return (identity_object, state_object), tuple(rows)


def team_state_advancement_write_plan(
    advancement: TeamStateAdvancement,
    *,
    initial_elo_ratings: Mapping[UUID, float],
) -> AggregateWritePlan:
    """Persist pre/post state and exactly-once applied-result lineage atomically."""

    initial_payload = initial_elo_bytes(initial_elo_ratings)
    if sha256_bytes(initial_payload) != advancement.pre_state.initial_elo_sha256:
        raise RepositoryContractError("state initial Elo bytes changed")
    advancement_id, checksum, identity_bytes = team_state_advancement_identity(
        prior_advancement_id=advancement.prior_advancement_id,
        pre_state=advancement.pre_state,
        post_state=advancement.post_state,
        applied_results=advancement.applied_results,
    )
    if advancement_id != advancement.id or checksum != advancement.identity_sha256:
        raise RepositoryContractError("team-state advancement identity changed")
    pre_objects, pre_rows = _state_objects_and_rows(advancement.pre_state)
    post_objects, post_rows = _state_objects_and_rows(advancement.post_state)
    advancement_object = _json_object(
        canonical_json_bytes(advancement), "team-state-advancement-v1"
    )
    objects = {
        item.sha256: item
        for item in (
            *pre_objects,
            *post_objects,
            _json_object(initial_payload, "prediction-initial-elo-v1"),
            _json_object(identity_bytes, "team-state-advancement-identity-v1"),
            advancement_object,
        )
    }
    rows = [*pre_rows, *post_rows]
    rows.append(
        ImmutableRow.build(
            PersistenceTable.TEAM_STATE_ADVANCEMENT,
            {
                "advancement_id": advancement.id,
                "identity_sha256": advancement.identity_sha256,
                "advancement_object_sha256": advancement_object.sha256,
                "schema_version": advancement.schema_version,
                "competition_id": "eng-premier-league",
                "season_id": advancement.post_state.season_id,
                "prior_advancement_id": advancement.prior_advancement_id,
                "pre_state_id": advancement.pre_state.id,
                "pre_state_sha256": advancement.pre_state.identity_sha256,
                "post_state_id": advancement.post_state.id,
                "post_state_sha256": advancement.post_state.identity_sha256,
                "applied_at": advancement.applied_at,
                "applied_result_count": len(advancement.applied_results),
            },
            identity_columns=("advancement_id",),
        )
    )
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.TEAM_STATE_ADVANCEMENT_RESULT,
            {
                "advancement_id": advancement.id,
                "ordinal": ordinal,
                "evaluation_id": item.evaluation.id,
                "evaluation_identity_sha256": item.evaluation.identity_sha256,
                "result_id": item.result.result_id,
                "result_identity_sha256": item.result.result_identity_sha256,
                "fixture_id": item.result.fixture.id,
            },
            identity_columns=("advancement_id", "ordinal"),
        )
        for ordinal, item in enumerate(advancement.applied_results)
    )
    return AggregateWritePlan(
        kind=AggregateKind.TEAM_STATE_ADVANCEMENTS,
        identity=advancement.identity_sha256,
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(
            sorted(rows, key=lambda row: list(PersistenceTable).index(row.table))
        ),
    )


def prediction_regeneration_write_plan(
    regenerations: Sequence[PredictionRegeneration],
    *,
    opening_priors: Mapping[UUID, SeasonOpeningPrior],
    initial_elo_ratings: Mapping[UUID, float],
) -> AggregateWritePlan:
    """Atomically store replacement features, predictions and supersession links."""

    if not regenerations or len({item.id for item in regenerations}) != len(
        regenerations
    ):
        raise RepositoryContractError("prediction regenerations must be unique")
    feature_plan = upcoming_features_write_plan(
        tuple(item.replacement_feature for item in regenerations),
        opening_priors=opening_priors,
        initial_elo_ratings=initial_elo_ratings,
    )
    prediction_plan = predictions_write_plan(
        tuple(item.replacement_prediction for item in regenerations)
    )
    objects = {
        item.sha256: item for item in (*feature_plan.objects, *prediction_plan.objects)
    }
    rows = [*feature_plan.rows, *prediction_plan.rows]
    for item in sorted(regenerations, key=lambda value: value.id):
        expected_id, checksum, identity_bytes = prediction_regeneration_identity(
            advancement_id=item.advancement_id,
            advancement_identity_sha256=item.advancement_identity_sha256,
            prior_prediction=item.prior_prediction,
            replacement_prediction=item.replacement_prediction,
        )
        if expected_id != item.id or checksum != item.identity_sha256:
            raise RepositoryContractError("prediction regeneration identity changed")
        record_object = _json_object(
            canonical_json_bytes(item), "prediction-regeneration-v1"
        )
        for obj in (
            _json_object(identity_bytes, "prediction-regeneration-identity-v1"),
            record_object,
        ):
            objects[obj.sha256] = obj
        rows.append(
            ImmutableRow.build(
                PersistenceTable.PREDICTION_REGENERATION,
                {
                    "regeneration_id": item.id,
                    "identity_sha256": item.identity_sha256,
                    "regeneration_object_sha256": record_object.sha256,
                    "schema_version": item.schema_version,
                    "advancement_id": item.advancement_id,
                    "advancement_identity_sha256": item.advancement_identity_sha256,
                    "prior_prediction_id": item.prior_prediction.id,
                    "prior_prediction_identity_sha256": (
                        item.prior_prediction.identity_sha256
                    ),
                    "replacement_prediction_id": item.replacement_prediction.id,
                    "replacement_prediction_identity_sha256": (
                        item.replacement_prediction.identity_sha256
                    ),
                    "fixture_id": item.prior_prediction.fixture_id,
                    "season_id": item.prior_prediction.season_id,
                },
                identity_columns=("regeneration_id",),
            )
        )
    return AggregateWritePlan(
        kind=AggregateKind.PREDICTION_REGENERATIONS,
        identity=sha256_bytes(
            canonical_json_bytes(
                {
                    "regeneration_ids": [
                        str(item.id)
                        for item in sorted(regenerations, key=lambda value: value.id)
                    ]
                }
            )
        ),
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(
            sorted(rows, key=lambda row: list(PersistenceTable).index(row.table))
        ),
    )


def _array_object(
    value: npt.NDArray[np.generic],
    *,
    format_id: str,
) -> StoredObject:
    canonical = np.ascontiguousarray(value).astype(
        value.dtype.newbyteorder("<"), copy=False
    )
    stream = BytesIO()
    np.save(stream, canonical, allow_pickle=False)
    return StoredObject.from_bytes(
        stream.getvalue(),
        media_type="application/x-npy",
        encoding=None,
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.NUMPY_ARRAY,
    )


def _distribution_rows(
    distribution: FixtureScorelineDistribution,
) -> tuple[StoredObject, tuple[ImmutableRow, ...]]:
    identity_bytes = scoreline_distribution_identity_bytes(distribution)
    identity_object = _identity_object(
        identity_bytes, "scoreline-distribution-identity-v1"
    )
    rows = [
        ImmutableRow.build(
            PersistenceTable.SCORELINE_DISTRIBUTION,
            {
                "distribution_id": distribution.id,
                "identity_sha256": identity_object.sha256,
                "schema_version": distribution.schema_version,
                "fixture_id": distribution.fixture_id,
                "home_team_id": distribution.home_team_id,
                "away_team_id": distribution.away_team_id,
            },
            identity_columns=("distribution_id",),
        )
    ]
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.SCORELINE_PROBABILITY,
            {
                "distribution_id": distribution.id,
                "score_ordinal": ordinal,
                "home_goals": item.scoreline.home_goals,
                "away_goals": item.scoreline.away_goals,
                "probability": item.probability,
            },
            identity_columns=("distribution_id", "score_ordinal"),
        )
        for ordinal, item in enumerate(distribution.probabilities)
    )
    return identity_object, tuple(rows)


def simulation_regeneration_write_plan(
    bundle: SimulationRegenerationBundle,
) -> AggregateWritePlan:
    """Persist approved inputs, exact matrices, summary and regeneration lineage."""

    regeneration = bundle.regeneration
    input_bytes = canonical_json_bytes(bundle.simulation_input)
    if sha256_bytes(input_bytes) != regeneration.replacement_input_sha256:
        raise RepositoryContractError("simulation input checksum changed")
    objects: dict[str, StoredObject] = {}
    rows: list[ImmutableRow] = []
    provenance_by_distribution = {
        item.fixture.scoreline_distribution.id: item.provenance
        for item in bundle.approved_fixtures
    }
    for approved in sorted(
        bundle.approved_fixtures,
        key=lambda item: item.fixture.scoreline_distribution.id,
    ):
        distribution = approved.fixture.scoreline_distribution
        distribution_object, distribution_rows = _distribution_rows(distribution)
        objects[distribution_object.sha256] = distribution_object
        rows.extend(distribution_rows)
        provenance = approved.provenance
        provenance_id, checksum, provenance_bytes = distribution_provenance_identity(
            distribution_id=provenance.distribution_id,
            input_sha256=provenance.input_sha256,
            producer_identity=provenance.producer_identity,
            producer_version=provenance.producer_version,
            runtime_contract=provenance.runtime_contract,
            numerical_contract=provenance.numerical_contract,
            approval_context=provenance.approval_context,
        )
        if provenance_id != provenance.id or checksum != provenance.identity_sha256:
            raise RepositoryContractError("distribution provenance identity changed")
        provenance_object = _json_object(
            provenance_bytes, "distribution-provenance-identity-v1"
        )
        objects[provenance_object.sha256] = provenance_object
        rows.append(
            ImmutableRow.build(
                PersistenceTable.DISTRIBUTION_PROVENANCE,
                {
                    "provenance_id": provenance.id,
                    "identity_sha256": provenance.identity_sha256,
                    "distribution_id": provenance.distribution_id,
                    "producer_kind": provenance.producer_kind,
                    "producer_identity": provenance.producer_identity,
                    "producer_version": provenance.producer_version,
                    "input_sha256": provenance.input_sha256,
                    "artifact_id": None,
                    "runtime_contract": provenance.runtime_contract,
                    "numerical_contract": provenance.numerical_contract,
                    "approval_context": provenance.approval_context,
                },
                identity_columns=("provenance_id",),
            )
        )
    input_object = _json_object(input_bytes, "season-simulation-input-v1")
    objects[input_object.sha256] = input_object
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_INPUT,
            {
                "input_sha256": input_object.sha256,
                "schema_version": bundle.simulation_input.schema_version,
                "competition_id": bundle.simulation_input.competition_id,
                "season_id": bundle.simulation_input.season_id,
            },
            identity_columns=("input_sha256",),
        )
    )
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_INPUT_TEAM,
            {
                "input_sha256": input_object.sha256,
                "ordinal": ordinal,
                "team_id": team_id,
            },
            identity_columns=("input_sha256", "ordinal"),
        )
        for ordinal, team_id in enumerate(bundle.simulation_input.team_ids)
    )
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_INPUT_COMPLETED_FIXTURE,
            {
                "input_sha256": input_object.sha256,
                "ordinal": ordinal,
                "fixture_id": item.fixture_id,
                "home_team_id": item.home_team_id,
                "away_team_id": item.away_team_id,
                "home_goals": item.scoreline.home_goals,
                "away_goals": item.scoreline.away_goals,
                "outcome": item.scoreline.outcome.value,
            },
            identity_columns=("input_sha256", "ordinal"),
        )
        for ordinal, item in enumerate(bundle.simulation_input.completed_matches)
    )
    batches = simulation_fixture_batches(bundle.simulation_input.remaining_fixtures)
    batch_for_fixture: dict[UUID, tuple[int, int]] = {}
    for batch_ordinal, batch in enumerate(batches):
        first = batch.fixtures[0]
        competition_date = first.kickoff_at.astimezone(_LONDON).date()
        rows.append(
            ImmutableRow.build(
                PersistenceTable.SIMULATION_INPUT_BATCH,
                {
                    "input_sha256": input_object.sha256,
                    "batch_ordinal": batch_ordinal,
                    "batch_kind": (
                        "date_only_date"
                        if batch.is_date_only_batch
                        else "exact_kickoff"
                    ),
                    "competition_date": competition_date,
                    "exact_kickoff_at": None
                    if batch.is_date_only_batch
                    else first.kickoff_at,
                },
                identity_columns=("input_sha256", "batch_ordinal"),
            )
        )
        for member_ordinal, fixture in enumerate(batch.fixtures):
            batch_for_fixture[fixture.fixture_id] = (batch_ordinal, member_ordinal)
    rows.extend(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_INPUT_REMAINING_FIXTURE,
            {
                "input_sha256": input_object.sha256,
                "ordinal": ordinal,
                "fixture_id": item.fixture_id,
                "competition_id": bundle.simulation_input.competition_id,
                "season_id": item.season_id,
                "home_team_id": item.home_team_id,
                "away_team_id": item.away_team_id,
                "kickoff_at": item.kickoff_at,
                "kickoff_precision": item.kickoff_precision.value,
                "distribution_id": item.scoreline_distribution.id,
                "provenance_id": provenance_by_distribution[
                    item.scoreline_distribution.id
                ].id,
                "batch_ordinal": batch_for_fixture[item.fixture_id][0],
                "batch_member_ordinal": batch_for_fixture[item.fixture_id][1],
            },
            identity_columns=("input_sha256", "ordinal"),
        )
        for ordinal, item in enumerate(bundle.simulation_input.remaining_fixtures)
    )
    run_identity_bytes = simulation_identity_bytes(
        bundle.simulation_input, bundle.result.simulation_seed
    )
    run_identity_object = _identity_object(
        run_identity_bytes, "season-simulation-run-identity-v1"
    )
    objects[run_identity_object.sha256] = run_identity_object
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_RUN,
            {
                "simulation_id": bundle.result.simulation_id,
                "identity_sha256": run_identity_object.sha256,
                "input_sha256": input_object.sha256,
                "schema_version": 1,
                "algorithm_version": SIMULATION_ALGORITHM_VERSION,
                "simulation_seed": bundle.result.simulation_seed,
                "simulation_count": SIMULATION_COUNT,
            },
            identity_columns=("simulation_id",),
        )
    )
    components = (
        ("points", bundle.result.points, ("run", "team")),
        ("goals_for", bundle.result.goals_for, ("run", "team")),
        ("goals_against", bundle.result.goals_against, ("run", "team")),
        ("sampled_home_goals", bundle.result.sampled_home_goals, ("run", "fixture")),
        ("sampled_away_goals", bundle.result.sampled_away_goals, ("run", "fixture")),
        ("position_mass", bundle.result.position_mass, ("run", "team", "position")),
    )
    for role, array, axes in components:
        component = _array_object(array, format_id=f"simulation-{role}-npy-v1")
        objects[component.sha256] = component
        rows.append(
            ImmutableRow.build(
                PersistenceTable.RESULT_COMPONENT,
                {
                    "simulation_id": bundle.result.simulation_id,
                    "role": role,
                    "object_sha256": component.sha256,
                    "dtype": array.dtype.name,
                    "shape": tuple(int(value) for value in array.shape),
                    "axis_order": axes,
                },
                identity_columns=("simulation_id", "role"),
            )
        )
    summary_identity = _identity_object(
        simulation_summary_identity_bytes(
            bundle.summary.simulation_id,
            bundle.summary.season_id,
            bundle.summary.teams,
        ),
        "season-simulation-summary-identity-v1",
    )
    summary_object = _json_object(
        canonical_json_bytes(bundle.summary), "season-simulation-summary-v1"
    )
    objects[summary_identity.sha256] = summary_identity
    objects[summary_object.sha256] = summary_object
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SIMULATION_SUMMARY,
            {
                "summary_id": bundle.summary.summary_id,
                "identity_sha256": summary_identity.sha256,
                "simulation_id": bundle.summary.simulation_id,
                "summary_sha256": summary_object.sha256,
                "schema_version": bundle.summary.schema_version,
                "algorithm_version": bundle.summary.algorithm_version,
                "simulation_count": bundle.summary.simulation_count,
                "season_id": bundle.summary.season_id,
            },
            identity_columns=("summary_id",),
        )
    )
    for team_ordinal, team in enumerate(bundle.summary.teams):
        rows.append(
            ImmutableRow.build(
                PersistenceTable.TEAM_SUMMARY,
                {
                    "summary_id": bundle.summary.summary_id,
                    "team_id": team.team_id,
                    "team_ordinal": team_ordinal,
                    "expected_points": team.expected_points,
                    "expected_goals_for": team.expected_goals_for,
                    "expected_goals_against": team.expected_goals_against,
                    "expected_goal_difference": team.expected_goal_difference,
                    "champion_probability": team.champion_probability,
                    "top_four_probability": team.top_four_probability,
                    "top_six_probability": team.top_six_probability,
                    "relegation_probability": team.relegation_probability,
                },
                identity_columns=("summary_id", "team_id"),
            )
        )
        rows.extend(
            ImmutableRow.build(
                PersistenceTable.POSITION_PROBABILITY,
                {
                    "summary_id": bundle.summary.summary_id,
                    "team_id": team.team_id,
                    "position": position,
                    "probability": probability,
                },
                identity_columns=("summary_id", "team_id", "position"),
            )
            for position, probability in enumerate(team.position_probabilities, start=1)
        )
    expected_id, checksum, regeneration_identity_bytes = (
        season_simulation_regeneration_identity(
            advancement_id=regeneration.advancement_id,
            advancement_identity_sha256=regeneration.advancement_identity_sha256,
            previous_simulation_id=regeneration.previous_simulation_id,
            replacement_input_sha256=regeneration.replacement_input_sha256,
            replacement_simulation_id=regeneration.replacement_simulation_id,
            replacement_summary_id=regeneration.replacement_summary_id,
            simulation_seed=regeneration.simulation_seed,
            season_id=regeneration.season_id,
        )
    )
    if expected_id != regeneration.id or checksum != regeneration.identity_sha256:
        raise RepositoryContractError("simulation regeneration identity changed")
    regeneration_object = _json_object(
        canonical_json_bytes(regeneration), "season-simulation-regeneration-v1"
    )
    for obj in (
        _json_object(
            regeneration_identity_bytes,
            "season-simulation-regeneration-identity-v1",
        ),
        regeneration_object,
    ):
        objects[obj.sha256] = obj
    rows.append(
        ImmutableRow.build(
            PersistenceTable.SEASON_SIMULATION_REGENERATION,
            {
                "regeneration_id": regeneration.id,
                "identity_sha256": regeneration.identity_sha256,
                "regeneration_object_sha256": regeneration_object.sha256,
                "schema_version": regeneration.schema_version,
                "advancement_id": regeneration.advancement_id,
                "advancement_identity_sha256": regeneration.advancement_identity_sha256,
                "previous_simulation_id": regeneration.previous_simulation_id,
                "replacement_input_sha256": regeneration.replacement_input_sha256,
                "replacement_simulation_id": regeneration.replacement_simulation_id,
                "replacement_summary_id": regeneration.replacement_summary_id,
                "simulation_seed": regeneration.simulation_seed,
                "season_id": regeneration.season_id,
            },
            identity_columns=("regeneration_id",),
        )
    )
    return AggregateWritePlan(
        kind=AggregateKind.SIMULATION_REGENERATIONS,
        identity=regeneration.identity_sha256,
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(
            sorted(rows, key=lambda row: list(PersistenceTable).index(row.table))
        ),
    )


class PredictionOperationsRepository:
    """Raw-manifest-gated persistence façade for Steps 7.5 through 7.7."""

    def __init__(self, repository: PostgresAggregateRepository) -> None:
        self._repository = repository

    def store_advancement(
        self,
        advancement: TeamStateAdvancement,
        *,
        initial_elo_ratings: Mapping[UUID, float],
    ) -> PersistenceResult:
        return self._repository.persist(
            team_state_advancement_write_plan(
                advancement, initial_elo_ratings=initial_elo_ratings
            )
        )

    def store_prediction_regenerations(
        self,
        regenerations: Sequence[PredictionRegeneration],
        *,
        opening_priors: Mapping[UUID, SeasonOpeningPrior],
        initial_elo_ratings: Mapping[UUID, float],
    ) -> PersistenceResult:
        return self._repository.persist(
            prediction_regeneration_write_plan(
                regenerations,
                opening_priors=opening_priors,
                initial_elo_ratings=initial_elo_ratings,
            )
        )

    def store_simulation_regeneration(
        self, bundle: SimulationRegenerationBundle
    ) -> PersistenceResult:
        return self._repository.persist(simulation_regeneration_write_plan(bundle))
