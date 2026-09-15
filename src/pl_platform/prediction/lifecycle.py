"""Deterministic upcoming-feature, prediction and completion workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import fsum, log
from typing import Literal, cast
from uuid import UUID

from pl_platform.domain.evaluation import OUTCOME_ORDER
from pl_platform.domain.fixtures import Fixture
from pl_platform.domain.seasons import PremierLeagueSeason
from pl_platform.features.chronology import chronological_fixture_batches
from pl_platform.features.engine import (
    PREDICTOR_SCHEMA_ID,
    PREDICTOR_SCHEMA_VERSION,
    build_upcoming_predictor_set,
)
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.registry.active_model import LoadedActiveModel
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes

from .domain import (
    SEALED_TEST_SEASON_ID,
    CompletedPredictionEvaluation,
    CompletedResultEvidence,
    CurrentFixtureEvidence,
    CurrentModelPrediction,
    PredictionLifecycleError,
    UpcomingFeatureRow,
    completed_evaluation_identity,
    current_prediction_identity,
    upcoming_feature_identity,
)
from .domain import PredictionLifecycleFailureCode as Failure


def opening_priors_bytes(
    opening_priors: Mapping[UUID, SeasonOpeningPrior],
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "values": [
                {
                    "prior": opening_priors[team_id].model_dump(mode="json"),
                    "team_id": str(team_id),
                }
                for team_id in sorted(opening_priors)
            ],
        }
    )


def initial_elo_bytes(initial_elo_ratings: Mapping[UUID, float]) -> bytes:
    return canonical_json_bytes(
        {
            "elo_schema_version": 1,
            "values": [
                {"rating": float(initial_elo_ratings[team_id]), "team_id": str(team_id)}
                for team_id in sorted(initial_elo_ratings)
            ],
        }
    )


def completed_state_bytes(results: Sequence[CompletedResultEvidence]) -> bytes:
    """Return canonical exact bytes for an ordered current-result state."""

    return canonical_json_bytes(
        {
            "schema_version": 1,
            "results": [item.model_dump(mode="json") for item in results],
        }
    )


def _validate_upcoming_batches(fixtures: Sequence[CurrentFixtureEvidence]) -> None:
    by_id = {item.fixture.id: item for item in fixtures}
    upcoming = tuple(item.fixture for item in fixtures)
    for batch in chronological_fixture_batches(upcoming):
        evidence = tuple(by_id[item.id] for item in batch.fixtures)
        if len({item.batch_id for item in evidence}) != 1:
            raise PredictionLifecycleError(
                Failure.CHRONOLOGY_VIOLATION,
                "one simultaneous fixture batch has multiple source batch identities",
            )
        expected_kind = (
            "date_only_date" if batch.is_date_only_batch else "exact_kickoff"
        )
        if any(item.batch_kind != expected_kind for item in evidence):
            raise PredictionLifecycleError(
                Failure.CHRONOLOGY_VIOLATION,
                "source batch kind does not match conservative chronology",
            )
        if len({item.knowledge_available_at for item in evidence}) != 1:
            raise PredictionLifecycleError(
                Failure.CHRONOLOGY_VIOLATION,
                "simultaneous fixtures do not share one knowledge boundary",
            )
        if tuple(item.batch_member_ordinal for item in evidence) != tuple(
            range(len(evidence))
        ):
            raise PredictionLifecycleError(
                Failure.CHRONOLOGY_VIOLATION,
                "source batch member ordinals are incomplete or noncanonical",
            )


def _relevant_results(
    fixture: CurrentFixtureEvidence,
    results: Sequence[CompletedResultEvidence],
) -> tuple[CompletedResultEvidence, ...]:
    known = tuple(
        item for item in results if item.retrieved_at <= fixture.knowledge_available_at
    )
    combined = (*tuple(item.fixture for item in known), fixture.fixture)
    batches = chronological_fixture_batches(combined)
    upcoming_index = next(
        index
        for index, batch in enumerate(batches)
        if fixture.fixture.id in {item.id for item in batch.fixtures}
    )
    batch_by_fixture = {
        item.id: index for index, batch in enumerate(batches) for item in batch.fixtures
    }
    if any(batch_by_fixture[item.fixture.id] >= upcoming_index for item in known):
        raise PredictionLifecycleError(
            Failure.CHRONOLOGY_VIOLATION,
            "known completed state does not strictly precede the upcoming batch",
        )
    return tuple(
        sorted(known, key=lambda item: (item.fixture.kickoff_at, item.fixture.id))
    )


def build_upcoming_feature_rows(
    *,
    fixtures: Sequence[CurrentFixtureEvidence],
    completed_results: Sequence[CompletedResultEvidence],
    season: PremierLeagueSeason,
    opening_priors: Mapping[UUID, SeasonOpeningPrior],
    initial_elo_ratings: Mapping[UUID, float],
    historical_context_sha256: str,
) -> tuple[UpcomingFeatureRow, ...]:
    """Build deterministic, unlabelled point-in-time rows for scheduled fixtures."""

    if season.id == SEALED_TEST_SEASON_ID:
        raise PredictionLifecycleError(
            Failure.SEALED_TARGET_PROHIBITED,
            "the frozen 2025-2026 season is not operational input",
        )
    if not fixtures:
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "upcoming feature generation requires fixtures",
        )
    if len({item.fixture.id for item in fixtures}) != len(fixtures):
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "upcoming fixture evidence repeats an identity",
        )
    if len({item.fixture.id for item in completed_results}) != len(completed_results):
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "completed-result evidence repeats an identity",
        )
    wrong_fixture_scope = any(
        item.fixture.competition_id != season.competition_id
        or item.fixture.season_id != season.id
        for item in fixtures
    )
    wrong_result_scope = any(
        item.fixture.competition_id != season.competition_id
        or item.fixture.season_id != season.id
        for item in completed_results
    )
    if wrong_fixture_scope or wrong_result_scope:
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "current evidence does not match the season scope",
        )
    if set(opening_priors) != set(season.team_ids) or set(initial_elo_ratings) != set(
        season.team_ids
    ):
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "opening priors and initial Elo must cover the exact season membership",
        )
    if len(historical_context_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in historical_context_sha256
    ):
        raise PredictionLifecycleError(
            Failure.PROVENANCE_MISMATCH,
            "historical context checksum is invalid",
        )
    _validate_upcoming_batches(fixtures)

    prior_bytes = opening_priors_bytes(opening_priors)
    elo_bytes = initial_elo_bytes(initial_elo_ratings)
    prior_sha256 = sha256_bytes(prior_bytes)
    elo_sha256 = sha256_bytes(elo_bytes)
    rows: list[UpcomingFeatureRow] = []
    for evidence in sorted(
        fixtures,
        key=lambda item: (
            item.knowledge_available_at,
            item.fixture.kickoff_at,
            item.fixture.id,
        ),
    ):
        relevant = _relevant_results(evidence, completed_results)
        predictors = build_upcoming_predictor_set(
            tuple(item.fixture for item in relevant),
            evidence.fixture,
            season,
            opening_priors=opening_priors,
            initial_elo_ratings=initial_elo_ratings,
        )
        if (
            predictors.schema_id != PREDICTOR_SCHEMA_ID
            or predictors.schema_version != PREDICTOR_SCHEMA_VERSION
            or len(predictors.values) != 175
        ):
            raise PredictionLifecycleError(
                Failure.PREDICTOR_SCHEMA_INCOMPATIBLE,
                "upcoming predictors do not match schema epl-pre-match v2",
            )
        feature_id, identity_sha256, _ = upcoming_feature_identity(
            fixture_evidence=evidence,
            feature_cutoff_at=evidence.knowledge_available_at,
            predictors=predictors,
            completed_results=relevant,
            historical_context_sha256=historical_context_sha256,
            opening_priors_sha256=prior_sha256,
            initial_elo_sha256=elo_sha256,
        )
        rows.append(
            UpcomingFeatureRow(
                id=feature_id,
                identity_sha256=identity_sha256,
                fixture_evidence=evidence,
                fixture_id=evidence.fixture.id,
                competition_id="eng-premier-league",
                season_id=evidence.fixture.season_id,
                home_team_id=evidence.fixture.home_team_id,
                away_team_id=evidence.fixture.away_team_id,
                kickoff_at=evidence.fixture.kickoff_at,
                feature_cutoff_at=evidence.knowledge_available_at,
                predictors=predictors,
                predictor_payload_sha256=sha256_bytes(canonical_json_bytes(predictors)),
                completed_results=relevant,
                historical_context_sha256=historical_context_sha256,
                opening_priors_sha256=prior_sha256,
                initial_elo_sha256=elo_sha256,
            )
        )
    return tuple(rows)


def generate_current_predictions(
    features: Sequence[UpcomingFeatureRow],
    active_model: LoadedActiveModel,
) -> tuple[CurrentModelPrediction, ...]:
    """Generate target-free three-way probabilities from one verified active model."""

    if active_model.registry.state != "active":
        raise PredictionLifecycleError(
            Failure.ACTIVE_MODEL_REQUIRED,
            "prediction requires an explicitly active registry head",
        )
    if not features:
        raise PredictionLifecycleError(
            Failure.INVALID_FEATURE_INPUT,
            "prediction generation requires feature rows",
        )
    entry = active_model.registry.entry
    manifest = active_model.artifact.manifest
    configuration_id = manifest.model.classifier.configuration.id
    if configuration_id != "catboost-depth6-regularized":
        raise PredictionLifecycleError(
            Failure.PREDICTION_FAILED,
            "active model configuration is unsupported",
        )
    supported_configuration = cast(
        Literal["catboost-depth6-regularized"], configuration_id
    )
    predictions: list[CurrentModelPrediction] = []
    for feature in sorted(
        features, key=lambda item: (item.feature_cutoff_at, item.kickoff_at, item.id)
    ):
        if (
            feature.predictors.schema_id != manifest.predictors.predictor_schema.id
            or feature.predictors.schema_version
            != manifest.predictors.predictor_schema.version
            or tuple(item.name for item in feature.predictors.values)
            != manifest.predictors.predictor_schema.predictor_names
        ):
            raise PredictionLifecycleError(
                Failure.PREDICTOR_SCHEMA_INCOMPATIBLE,
                "feature predictors do not match the active model",
            )
        try:
            probabilities = active_model.artifact.classifier.predict_probabilities(
                feature.predictors
            )
        except (RuntimeError, ValueError) as exc:
            raise PredictionLifecycleError(
                Failure.PREDICTION_FAILED,
                "active classifier could not produce probabilities",
            ) from exc
        prediction_id, identity_sha256, _ = current_prediction_identity(
            feature_id=feature.id,
            feature_identity_sha256=feature.identity_sha256,
            registry_entry_id=entry.entry_id,
            registry_head_event_id=active_model.registry.head_event_id,
            registry_head_event_sha256=active_model.registry.head_event_sha256,
            model_id=manifest.model_id,
            artifact_id=manifest.artifact_id,
            manifest_id=manifest.manifest_id,
            artifact_manifest_sha256=entry.artifact_manifest_sha256,
            configuration_id=supported_configuration,
        )
        predictions.append(
            CurrentModelPrediction(
                id=prediction_id,
                identity_sha256=identity_sha256,
                feature_id=feature.id,
                feature_identity_sha256=feature.identity_sha256,
                fixture_id=feature.fixture_evidence.fixture.id,
                competition_id=feature.competition_id,
                season_id=feature.season_id,
                home_team_id=feature.home_team_id,
                away_team_id=feature.away_team_id,
                kickoff_at=feature.kickoff_at,
                feature_cutoff_at=feature.feature_cutoff_at,
                registry_entry_id=entry.entry_id,
                registry_head_event_id=active_model.registry.head_event_id,
                registry_head_event_sha256=active_model.registry.head_event_sha256,
                model_id=manifest.model_id,
                artifact_id=manifest.artifact_id,
                manifest_id=manifest.manifest_id,
                artifact_manifest_sha256=entry.artifact_manifest_sha256,
                configuration_id=supported_configuration,
                probabilities=probabilities,
            )
        )
    return tuple(predictions)


def evaluate_completed_prediction(
    prediction: CurrentModelPrediction,
    result: CompletedResultEvidence,
) -> CompletedPredictionEvaluation:
    """Evaluate one immutable prediction against one official completed result."""

    fixture: Fixture = result.fixture
    if prediction.season_id == SEALED_TEST_SEASON_ID:
        raise PredictionLifecycleError(
            Failure.SEALED_TARGET_PROHIBITED,
            "the frozen 2025-2026 outcome cannot be evaluated",
        )
    if (
        prediction.fixture_id != fixture.id
        or prediction.competition_id != fixture.competition_id
        or prediction.season_id != fixture.season_id
        or prediction.home_team_id != fixture.home_team_id
        or prediction.away_team_id != fixture.away_team_id
        or fixture.outcome is None
    ):
        raise PredictionLifecycleError(
            Failure.RESULT_MISMATCH,
            "completed result does not match the prediction snapshot",
        )
    if result.retrieved_at <= prediction.feature_cutoff_at:
        raise PredictionLifecycleError(
            Failure.CHRONOLOGY_VIOLATION,
            "result evidence must follow the prediction cutoff",
        )
    actual = fixture.outcome
    actual_probability = prediction.probabilities.for_outcome(actual)
    if actual_probability <= 0.0:
        raise PredictionLifecycleError(
            Failure.ZERO_ACTUAL_PROBABILITY,
            "log loss is undefined for the observed outcome",
        )
    probabilities = tuple(
        prediction.probabilities.for_outcome(outcome) for outcome in OUTCOME_ORDER
    )
    observations = tuple(1.0 if outcome is actual else 0.0 for outcome in OUTCOME_ORDER)
    brier = fsum(
        (probability - observation) ** 2
        for probability, observation in zip(probabilities, observations, strict=True)
    )
    ranked = (
        fsum(
            (fsum(probabilities[:boundary]) - fsum(observations[:boundary])) ** 2
            for boundary in (1, 2)
        )
        / 2.0
    )
    evaluation_id, identity_sha256, _ = completed_evaluation_identity(
        prediction_id=prediction.id,
        prediction_identity_sha256=prediction.identity_sha256,
        result_id=result.result_id,
        result_identity_sha256=result.result_identity_sha256,
        result_observation_id=result.observation_id,
        result_cache_key_sha256=result.cache_key_sha256,
        result_retrieved_at=result.retrieved_at,
    )
    return CompletedPredictionEvaluation(
        id=evaluation_id,
        identity_sha256=identity_sha256,
        prediction_id=prediction.id,
        prediction_identity_sha256=prediction.identity_sha256,
        result_id=result.result_id,
        result_identity_sha256=result.result_identity_sha256,
        result_observation_id=result.observation_id,
        result_cache_key_sha256=result.cache_key_sha256,
        result_retrieved_at=result.retrieved_at,
        fixture_id=fixture.id,
        season_id=fixture.season_id,
        outcome=actual,
        probabilities=prediction.probabilities,
        actual_outcome_probability=actual_probability,
        log_loss=-log(actual_probability),
        multiclass_brier_score=brier,
        ranked_probability_score=ranked,
    )
