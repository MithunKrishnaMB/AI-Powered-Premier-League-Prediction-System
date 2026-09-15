"""Append-only state, prediction-regeneration and simulation workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.domain.simulation import (
    PlayedFixture,
    Scoreline,
    SeasonSimulationInput,
    SimulationFixture,
    scoreline_distribution_identity_bytes,
    simulation_fixture_batches,
)
from pl_platform.features.chronology import chronological_fixture_batches
from pl_platform.features.elo import update_elo_batch
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.registry.active_model import LoadedActiveModel
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes
from pl_platform.simulation.aggregate import (
    SeasonSimulationSummary,
    aggregate_simulations,
)
from pl_platform.simulation.vectorized import (
    VectorizedSimulationResult,
    simulate_season_10k,
)

from .domain import (
    AppliedPredictionResult,
    CompletedPredictionEvaluation,
    CompletedResultEvidence,
    CurrentFixtureEvidence,
    CurrentModelPrediction,
    ExplicitScorelineProvenance,
    OperationalTeamState,
    PredictionLifecycleError,
    PredictionRegeneration,
    SeasonSimulationRegeneration,
    TeamEloRating,
    TeamStateAdvancement,
    UpcomingFeatureRow,
    distribution_provenance_identity,
    prediction_regeneration_identity,
    season_simulation_regeneration_identity,
    team_state_advancement_identity,
    team_state_identity,
)
from .domain import PredictionLifecycleFailureCode as Failure
from .lifecycle import (
    build_upcoming_feature_rows,
    generate_current_predictions,
    initial_elo_bytes,
)


def _state(
    season_id: str,
    initial_elo_sha256: str,
    completed_results: tuple[CompletedResultEvidence, ...],
    ratings: Mapping[UUID, float],
) -> OperationalTeamState:
    elo_ratings = tuple(
        TeamEloRating(team_id=team_id, rating=float(ratings[team_id]))
        for team_id in sorted(ratings, key=lambda value: value.int)
    )
    state_id, checksum, _ = team_state_identity(
        season_id=season_id,
        initial_elo_sha256=initial_elo_sha256,
        completed_results=completed_results,
        elo_ratings=elo_ratings,
    )
    return OperationalTeamState(
        id=state_id,
        identity_sha256=checksum,
        season_id=season_id,
        initial_elo_sha256=initial_elo_sha256,
        completed_results=completed_results,
        elo_ratings=elo_ratings,
    )


def _replay_ratings(
    results: Sequence[CompletedResultEvidence],
    initial_elo_ratings: Mapping[UUID, float],
) -> dict[UUID, float]:
    ratings = dict(initial_elo_ratings)
    for batch in chronological_fixture_batches(tuple(item.fixture for item in results)):
        ratings = update_elo_batch(ratings, batch.fixtures)
    return ratings


def build_initial_team_state(
    season: PremierLeagueSeason,
    initial_elo_ratings: Mapping[UUID, float],
) -> OperationalTeamState:
    """Create the deterministic empty operational state for one season."""

    if season.id == "2025-2026":
        raise PredictionLifecycleError(
            Failure.SEALED_TARGET_PROHIBITED,
            "the frozen 2025-2026 season is not operational state",
        )
    if set(initial_elo_ratings) != set(season.team_ids):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "initial Elo must cover the exact season membership",
        )
    return _state(
        season.id,
        sha256_bytes(initial_elo_bytes(initial_elo_ratings)),
        (),
        initial_elo_ratings,
    )


def advance_team_state(
    *,
    season: PremierLeagueSeason,
    initial_elo_ratings: Mapping[UUID, float],
    evaluations: Sequence[CompletedPredictionEvaluation],
    results: Sequence[CompletedResultEvidence],
    previous_advancement: TeamStateAdvancement | None = None,
) -> TeamStateAdvancement:
    """Apply one official simultaneous result batch to Elo/team state once."""

    pre_state = (
        build_initial_team_state(season, initial_elo_ratings)
        if previous_advancement is None
        else previous_advancement.post_state
    )
    initial_sha256 = sha256_bytes(initial_elo_bytes(initial_elo_ratings))
    if (
        pre_state.season_id != season.id
        or pre_state.initial_elo_sha256 != initial_sha256
        or set(item.team_id for item in pre_state.elo_ratings) != set(season.team_ids)
    ):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "previous team state does not match the season and initial Elo",
        )
    replayed = _replay_ratings(pre_state.completed_results, initial_elo_ratings)
    observed = {item.team_id: item.rating for item in pre_state.elo_ratings}
    if replayed != observed:
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "previous Elo state does not match its completed-result ledger",
        )
    if not results or len({item.result_id for item in results}) != len(results):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "state advancement requires one unique result batch",
        )
    previous_result_ids = {item.result_id for item in pre_state.completed_results}
    if previous_result_ids.intersection(item.result_id for item in results):
        raise PredictionLifecycleError(
            Failure.RESULT_ALREADY_APPLIED,
            "a result is already present in operational state",
        )
    fixtures = tuple(item.fixture for item in results)
    batches = chronological_fixture_batches(fixtures)
    if len(batches) != 1:
        raise PredictionLifecycleError(
            Failure.CHRONOLOGY_VIOLATION,
            "one state advancement must contain exactly one simultaneous batch",
        )
    combined = (*tuple(item.fixture for item in pre_state.completed_results), *fixtures)
    combined_batches = chronological_fixture_batches(combined)
    new_fixture_ids = {item.id for item in fixtures}
    if {item.id for item in combined_batches[-1].fixtures} != new_fixture_ids:
        raise PredictionLifecycleError(
            Failure.CHRONOLOGY_VIOLATION,
            "new result batch must strictly follow operational state",
        )
    evaluations_by_result = {item.result_id: item for item in evaluations}
    if len(evaluations_by_result) != len(evaluations) or set(evaluations_by_result) != {
        item.result_id for item in results
    }:
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "every result must have exactly one immutable evaluation",
        )
    ordered_results = tuple(
        sorted(results, key=lambda item: (item.fixture.kickoff_at, item.fixture.id))
    )
    applied = tuple(
        _applied_result(evaluations_by_result[item.result_id], item)
        for item in ordered_results
    )
    post_results = (*pre_state.completed_results, *ordered_results)
    post_ratings = update_elo_batch(observed, batches[0].fixtures)
    post_state = _state(season.id, initial_sha256, post_results, post_ratings)
    prior_id = None if previous_advancement is None else previous_advancement.id
    advancement_id, checksum, _ = team_state_advancement_identity(
        prior_advancement_id=prior_id,
        pre_state=pre_state,
        post_state=post_state,
        applied_results=applied,
    )
    return TeamStateAdvancement(
        id=advancement_id,
        identity_sha256=checksum,
        prior_advancement_id=prior_id,
        pre_state=pre_state,
        post_state=post_state,
        applied_results=applied,
        applied_at=max(item.retrieved_at for item in ordered_results),
    )


def regenerate_future_predictions(
    *,
    advancement: TeamStateAdvancement,
    prior_features: Sequence[UpcomingFeatureRow],
    prior_predictions: Sequence[CurrentModelPrediction],
    refreshed_fixtures: Sequence[CurrentFixtureEvidence],
    season: PremierLeagueSeason,
    opening_priors: Mapping[UUID, SeasonOpeningPrior],
    initial_elo_ratings: Mapping[UUID, float],
    historical_context_sha256: str,
    active_model: LoadedActiveModel,
) -> tuple[PredictionRegeneration, ...]:
    """Replace exactly the future predictions made stale by an advancement."""

    features_by_id = {item.id: item for item in prior_features}
    predictions_by_fixture = {item.fixture_id: item for item in prior_predictions}
    evidence_by_fixture = {item.fixture.id: item for item in refreshed_fixtures}
    if (
        not prior_predictions
        or len(features_by_id) != len(prior_features)
        or len(predictions_by_fixture) != len(prior_predictions)
        or len(evidence_by_fixture) != len(refreshed_fixtures)
        or set(predictions_by_fixture) != set(evidence_by_fixture)
        or {item.feature_id for item in prior_predictions} != set(features_by_id)
    ):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "regeneration inputs must form a unique one-to-one fixture snapshot",
        )
    if advancement.post_state.initial_elo_sha256 != sha256_bytes(
        initial_elo_bytes(initial_elo_ratings)
    ):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "regeneration initial Elo differs from advanced state",
        )
    applied_ids = {item.result.result_id for item in advancement.applied_results}
    ordered_predictions = tuple(
        sorted(prior_predictions, key=lambda item: (item.kickoff_at, item.id))
    )
    stale_features: list[UpcomingFeatureRow] = []
    ordered_evidence: list[CurrentFixtureEvidence] = []
    for prediction in ordered_predictions:
        try:
            prior_feature = features_by_id[prediction.feature_id]
            evidence = evidence_by_fixture[prediction.fixture_id]
        except KeyError as exc:
            raise PredictionLifecycleError(
                Failure.STATE_CHAIN_INVALID,
                "prediction regeneration lineage is incomplete",
            ) from exc
        prior_result_ids = {item.result_id for item in prior_feature.completed_results}
        if applied_ids.issubset(prior_result_ids):
            raise PredictionLifecycleError(
                Failure.REGENERATION_NOT_REQUIRED,
                "prior prediction already includes the advanced state",
            )
        if evidence.knowledge_available_at < advancement.applied_at:
            raise PredictionLifecycleError(
                Failure.CHRONOLOGY_VIOLATION,
                "refreshed fixture evidence predates the applied result batch",
            )
        stale_features.append(prior_feature)
        ordered_evidence.append(evidence)
    replacement_features = build_upcoming_feature_rows(
        fixtures=ordered_evidence,
        completed_results=advancement.post_state.completed_results,
        season=season,
        opening_priors=opening_priors,
        initial_elo_ratings=initial_elo_ratings,
        historical_context_sha256=historical_context_sha256,
    )
    replacement_predictions = generate_current_predictions(
        replacement_features, active_model
    )
    replacements_by_fixture = {
        item.fixture_id: item for item in replacement_predictions
    }
    features_by_fixture = {item.fixture_id: item for item in replacement_features}
    regenerations: list[PredictionRegeneration] = []
    for prior_prediction, prior_feature in zip(
        ordered_predictions, stale_features, strict=True
    ):
        replacement = replacements_by_fixture[prior_prediction.fixture_id]
        replacement_feature = features_by_fixture[prior_prediction.fixture_id]
        regeneration_id, checksum, _ = prediction_regeneration_identity(
            advancement_id=advancement.id,
            advancement_identity_sha256=advancement.identity_sha256,
            prior_prediction=prior_prediction,
            replacement_prediction=replacement,
        )
        regenerations.append(
            PredictionRegeneration(
                id=regeneration_id,
                identity_sha256=checksum,
                advancement_id=advancement.id,
                advancement_identity_sha256=advancement.identity_sha256,
                prior_feature=prior_feature,
                prior_prediction=prior_prediction,
                replacement_feature=replacement_feature,
                replacement_prediction=replacement,
            )
        )
    return tuple(regenerations)


def _applied_result(
    evaluation: CompletedPredictionEvaluation,
    result: CompletedResultEvidence,
) -> AppliedPredictionResult:
    if (
        evaluation.result_id != result.result_id
        or evaluation.result_identity_sha256 != result.result_identity_sha256
        or evaluation.result_observation_id != result.observation_id
        or evaluation.result_cache_key_sha256 != result.cache_key_sha256
        or evaluation.result_retrieved_at != result.retrieved_at
        or evaluation.fixture_id != result.fixture.id
    ):
        raise PredictionLifecycleError(
            Failure.STATE_CHAIN_INVALID,
            "evaluation does not match its official result evidence",
        )
    return AppliedPredictionResult(evaluation=evaluation, result=result)


@dataclass(frozen=True, slots=True)
class ApprovedSimulationFixture:
    """A remaining fixture plus independent explicit scoreline approval."""

    fixture: SimulationFixture
    provenance: ExplicitScorelineProvenance

    def __post_init__(self) -> None:
        if self.provenance.distribution_id != self.fixture.scoreline_distribution.id:
            raise PredictionLifecycleError(
                Failure.SCORELINE_PROVENANCE_REQUIRED,
                "scoreline approval does not match its distribution",
            )
        identity_sha256 = sha256_bytes(
            scoreline_distribution_identity_bytes(self.fixture.scoreline_distribution)
        )
        if self.provenance.input_sha256 != identity_sha256:
            raise PredictionLifecycleError(
                Failure.SCORELINE_PROVENANCE_REQUIRED,
                "scoreline approval input checksum does not match",
            )


def approve_explicit_scoreline_distribution(
    fixture: SimulationFixture,
    *,
    producer_identity: str,
    producer_version: str,
    runtime_contract: str,
    numerical_contract: str,
    approval_context: str,
) -> ApprovedSimulationFixture:
    """Attach explicit, non-CatBoost provenance to a supplied distribution."""

    input_sha256 = sha256_bytes(
        scoreline_distribution_identity_bytes(fixture.scoreline_distribution)
    )
    provenance_id, checksum, _ = distribution_provenance_identity(
        distribution_id=fixture.scoreline_distribution.id,
        input_sha256=input_sha256,
        producer_identity=producer_identity,
        producer_version=producer_version,
        runtime_contract=runtime_contract,
        numerical_contract=numerical_contract,
        approval_context=approval_context,
    )
    return ApprovedSimulationFixture(
        fixture=fixture,
        provenance=ExplicitScorelineProvenance(
            id=provenance_id,
            identity_sha256=checksum,
            distribution_id=fixture.scoreline_distribution.id,
            input_sha256=input_sha256,
            producer_identity=producer_identity,
            producer_version=producer_version,
            runtime_contract=runtime_contract,
            numerical_contract=numerical_contract,
            approval_context=approval_context,
        ),
    )


@dataclass(frozen=True, slots=True)
class SimulationRegenerationBundle:
    """Exact inputs, matrices, aggregate and supersession record for persistence."""

    approved_fixtures: tuple[ApprovedSimulationFixture, ...]
    simulation_input: SeasonSimulationInput
    result: VectorizedSimulationResult
    summary: SeasonSimulationSummary
    regeneration: SeasonSimulationRegeneration


def regenerate_season_simulation(
    *,
    advancement: TeamStateAdvancement,
    previous_simulation_id: UUID,
    approved_fixtures: Sequence[ApprovedSimulationFixture],
    simulation_seed: int,
) -> SimulationRegenerationBundle:
    """Regenerate 10,000 runs from advanced results and approved scorelines."""

    post_state = advancement.post_state
    provenances = tuple(item.provenance.id for item in approved_fixtures)
    if len(provenances) != len(set(provenances)):
        raise PredictionLifecycleError(
            Failure.SCORELINE_PROVENANCE_REQUIRED,
            "remaining fixtures repeat a scoreline approval",
        )
    remaining = tuple(
        fixture
        for batch in simulation_fixture_batches(
            tuple(item.fixture for item in approved_fixtures)
        )
        for fixture in batch.fixtures
    )
    completed = tuple(
        sorted(
            (
                PlayedFixture(
                    fixture_id=item.fixture.id,
                    home_team_id=item.fixture.home_team_id,
                    away_team_id=item.fixture.away_team_id,
                    scoreline=Scoreline(
                        home_goals=item.fixture.full_time_score.home,
                        away_goals=item.fixture.full_time_score.away,
                    ),
                )
                for item in post_state.completed_results
                if item.fixture.full_time_score is not None
            ),
            key=lambda item: item.fixture_id.int,
        )
    )
    simulation_input = SeasonSimulationInput(
        season_id=post_state.season_id,
        team_ids=tuple(item.team_id for item in post_state.elo_ratings),
        completed_matches=completed,
        remaining_fixtures=remaining,
    )
    try:
        result = simulate_season_10k(simulation_input, simulation_seed=simulation_seed)
        summary = aggregate_simulations(result)
    except (RuntimeError, ValueError) as exc:
        raise PredictionLifecycleError(
            Failure.SIMULATION_FAILED,
            "deterministic season simulation failed",
        ) from exc
    if result.simulation_id == previous_simulation_id:
        raise PredictionLifecycleError(
            Failure.REGENERATION_NOT_REQUIRED,
            "advanced state did not change the simulation identity",
        )
    input_sha256 = sha256_bytes(canonical_json_bytes(simulation_input))
    regeneration_id, checksum, _ = season_simulation_regeneration_identity(
        advancement_id=advancement.id,
        advancement_identity_sha256=advancement.identity_sha256,
        previous_simulation_id=previous_simulation_id,
        replacement_input_sha256=input_sha256,
        replacement_simulation_id=result.simulation_id,
        replacement_summary_id=summary.summary_id,
        simulation_seed=simulation_seed,
        season_id=post_state.season_id,
    )
    return SimulationRegenerationBundle(
        approved_fixtures=tuple(approved_fixtures),
        simulation_input=simulation_input,
        result=result,
        summary=summary,
        regeneration=SeasonSimulationRegeneration(
            id=regeneration_id,
            identity_sha256=checksum,
            advancement_id=advancement.id,
            advancement_identity_sha256=advancement.identity_sha256,
            previous_simulation_id=previous_simulation_id,
            replacement_input_sha256=input_sha256,
            replacement_simulation_id=result.simulation_id,
            replacement_summary_id=summary.summary_id,
            simulation_seed=simulation_seed,
            season_id=post_state.season_id,
        ),
    )
