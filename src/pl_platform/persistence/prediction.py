"""Immutable PostgreSQL write plans for prediction lifecycle records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from pl_platform.domain.features import PredictorValue
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.prediction.domain import (
    CompletedPredictionEvaluation,
    CurrentModelPrediction,
    UpcomingFeatureRow,
    completed_evaluation_identity,
    current_prediction_identity,
    upcoming_feature_identity,
)
from pl_platform.prediction.lifecycle import (
    completed_state_bytes,
    initial_elo_bytes,
    opening_priors_bytes,
)
from pl_platform.registry.artifact_manifest import canonical_json_bytes, sha256_bytes

from .repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    DatabaseValue,
    ImmutableRow,
    PersistenceResult,
    PersistenceTable,
    PostgresAggregateRepository,
    RepositoryContractError,
    StoredObject,
)


def _canonical_object(payload: bytes, *, format_id: str) -> StoredObject:
    return StoredObject.from_bytes(
        payload,
        media_type="application/json",
        encoding="utf-8",
        format_id=format_id,
        canonicalization_profile=CanonicalizationProfile.CANONICAL_JSON,
    )


def _predictor_columns(value: PredictorValue) -> dict[str, DatabaseValue]:
    scalar = value.value
    if scalar is None:
        return {
            "value_kind": "null",
            "boolean_value": None,
            "integer_value": None,
            "float64_value": None,
        }
    if isinstance(scalar, bool):
        return {
            "value_kind": "boolean",
            "boolean_value": scalar,
            "integer_value": None,
            "float64_value": None,
        }
    if isinstance(scalar, int):
        return {
            "value_kind": "integer",
            "boolean_value": None,
            "integer_value": scalar,
            "float64_value": None,
        }
    return {
        "value_kind": "float64",
        "boolean_value": None,
        "integer_value": None,
        "float64_value": scalar,
    }


def upcoming_features_write_plan(
    features: Sequence[UpcomingFeatureRow],
    *,
    opening_priors: Mapping[UUID, SeasonOpeningPrior],
    initial_elo_ratings: Mapping[UUID, float],
) -> AggregateWritePlan:
    """Build one exact-byte, current-evidence feature aggregate."""

    if not features:
        raise RepositoryContractError("upcoming feature persistence cannot be empty")
    if len({item.id for item in features}) != len(features):
        raise RepositoryContractError(
            "upcoming feature persistence repeats an identity"
        )
    prior_payload = opening_priors_bytes(opening_priors)
    elo_payload = initial_elo_bytes(initial_elo_ratings)
    prior_sha256 = sha256_bytes(prior_payload)
    elo_sha256 = sha256_bytes(elo_payload)
    if any(
        item.opening_priors_sha256 != prior_sha256
        or item.initial_elo_sha256 != elo_sha256
        for item in features
    ):
        raise RepositoryContractError("feature state payload checksums do not match")

    objects: dict[str, StoredObject] = {}
    prior_object = _canonical_object(
        prior_payload, format_id="prediction-opening-priors-v1"
    )
    elo_object = _canonical_object(elo_payload, format_id="prediction-initial-elo-v1")
    objects[prior_object.sha256] = prior_object
    objects[elo_object.sha256] = elo_object
    feature_rows: list[ImmutableRow] = []
    source_rows: list[ImmutableRow] = []
    value_rows: list[ImmutableRow] = []
    for feature in sorted(features, key=lambda item: item.id):
        identity, identity_sha256, identity_payload = upcoming_feature_identity(
            fixture_evidence=feature.fixture_evidence,
            feature_cutoff_at=feature.feature_cutoff_at,
            predictors=feature.predictors,
            completed_results=feature.completed_results,
            historical_context_sha256=feature.historical_context_sha256,
            opening_priors_sha256=feature.opening_priors_sha256,
            initial_elo_sha256=feature.initial_elo_sha256,
        )
        if identity != feature.id or identity_sha256 != feature.identity_sha256:
            raise RepositoryContractError("upcoming feature identity changed")
        identity_object = _canonical_object(
            identity_payload, format_id="prediction-upcoming-feature-identity-v1"
        )
        feature_object = _canonical_object(
            canonical_json_bytes(feature), format_id="prediction-upcoming-feature-v1"
        )
        state_object = _canonical_object(
            completed_state_bytes(feature.completed_results),
            format_id="prediction-completed-state-v1",
        )
        predictor_object = _canonical_object(
            canonical_json_bytes(feature.predictors),
            format_id="prediction-predictor-payload-v1",
        )
        for item in (identity_object, feature_object, state_object, predictor_object):
            objects[item.sha256] = item
        evidence = feature.fixture_evidence
        feature_rows.append(
            ImmutableRow.build(
                PersistenceTable.UPCOMING_FEATURE,
                {
                    "feature_id": feature.id,
                    "identity_sha256": feature.identity_sha256,
                    "feature_object_sha256": feature_object.sha256,
                    "schema_version": feature.schema_version,
                    "fixture_id": feature.fixture_id,
                    "fixture_revision_id": evidence.revision_id,
                    "fixture_revision_identity_sha256": (
                        evidence.revision_identity_sha256
                    ),
                    "fixture_observation_id": evidence.observation_id,
                    "fixture_cache_key_sha256": evidence.cache_key_sha256,
                    "fixture_batch_id": evidence.batch_id,
                    "fixture_batch_identity_sha256": evidence.batch_identity_sha256,
                    "fixture_batch_member_ordinal": evidence.batch_member_ordinal,
                    "competition_id": feature.competition_id,
                    "season_id": feature.season_id,
                    "home_team_id": feature.home_team_id,
                    "away_team_id": feature.away_team_id,
                    "kickoff_at": feature.kickoff_at,
                    "kickoff_precision": evidence.fixture.kickoff_precision.value,
                    "feature_cutoff_at": feature.feature_cutoff_at,
                    "predictor_schema_id": feature.predictors.schema_id,
                    "predictor_schema_version": feature.predictors.schema_version,
                    "predictor_payload_sha256": feature.predictor_payload_sha256,
                    "completed_state_sha256": state_object.sha256,
                    "historical_context_sha256": feature.historical_context_sha256,
                    "opening_priors_sha256": feature.opening_priors_sha256,
                    "initial_elo_sha256": feature.initial_elo_sha256,
                },
                identity_columns=("feature_id",),
            )
        )
        source_rows.extend(
            ImmutableRow.build(
                PersistenceTable.UPCOMING_FEATURE_RESULT_SOURCE,
                {
                    "feature_id": feature.id,
                    "ordinal": ordinal,
                    "result_id": result.result_id,
                    "result_identity_sha256": result.result_identity_sha256,
                    "fixture_id": result.fixture.id,
                    "result_observation_id": result.observation_id,
                    "cache_key_sha256": result.cache_key_sha256,
                    "retrieved_at": result.retrieved_at,
                },
                identity_columns=("feature_id", "ordinal"),
            )
            for ordinal, result in enumerate(feature.completed_results)
        )
        value_rows.extend(
            ImmutableRow.build(
                PersistenceTable.UPCOMING_FEATURE_VALUE,
                {
                    "feature_id": feature.id,
                    "predictor_ordinal": ordinal,
                    "predictor_schema_id": feature.predictors.schema_id,
                    "predictor_schema_version": feature.predictors.schema_version,
                    **_predictor_columns(value),
                },
                identity_columns=("feature_id", "predictor_ordinal"),
            )
            for ordinal, value in enumerate(feature.predictors.values)
        )
    aggregate_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "feature_ids": [
                    str(item.id) for item in sorted(features, key=lambda x: x.id)
                ]
            }
        )
    )
    return AggregateWritePlan(
        kind=AggregateKind.UPCOMING_FEATURES,
        identity=aggregate_sha256,
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(feature_rows + source_rows + value_rows),
    )


def predictions_write_plan(
    predictions: Sequence[CurrentModelPrediction],
) -> AggregateWritePlan:
    """Build an immutable prediction aggregate retaining active-model lineage."""

    if not predictions:
        raise RepositoryContractError("prediction persistence cannot be empty")
    if len({item.id for item in predictions}) != len(predictions):
        raise RepositoryContractError("prediction persistence repeats an identity")
    objects: dict[str, StoredObject] = {}
    rows: list[ImmutableRow] = []
    for prediction in sorted(predictions, key=lambda item: item.id):
        identity, checksum, identity_payload = current_prediction_identity(
            feature_id=prediction.feature_id,
            feature_identity_sha256=prediction.feature_identity_sha256,
            registry_entry_id=prediction.registry_entry_id,
            registry_head_event_id=prediction.registry_head_event_id,
            registry_head_event_sha256=prediction.registry_head_event_sha256,
            model_id=prediction.model_id,
            artifact_id=prediction.artifact_id,
            manifest_id=prediction.manifest_id,
            artifact_manifest_sha256=prediction.artifact_manifest_sha256,
            configuration_id=prediction.configuration_id,
        )
        if identity != prediction.id or checksum != prediction.identity_sha256:
            raise RepositoryContractError("current prediction identity changed")
        identity_object = _canonical_object(
            identity_payload, format_id="prediction-current-identity-v1"
        )
        prediction_object = _canonical_object(
            canonical_json_bytes(prediction), format_id="prediction-current-v1"
        )
        objects[identity_object.sha256] = identity_object
        objects[prediction_object.sha256] = prediction_object
        rows.append(
            ImmutableRow.build(
                PersistenceTable.CURRENT_MODEL_PREDICTION,
                {
                    "prediction_id": prediction.id,
                    "identity_sha256": prediction.identity_sha256,
                    "prediction_object_sha256": prediction_object.sha256,
                    "schema_version": prediction.schema_version,
                    "feature_id": prediction.feature_id,
                    "feature_identity_sha256": prediction.feature_identity_sha256,
                    "fixture_id": prediction.fixture_id,
                    "competition_id": prediction.competition_id,
                    "season_id": prediction.season_id,
                    "home_team_id": prediction.home_team_id,
                    "away_team_id": prediction.away_team_id,
                    "kickoff_at": prediction.kickoff_at,
                    "feature_cutoff_at": prediction.feature_cutoff_at,
                    "registry_entry_id": prediction.registry_entry_id,
                    "registry_head_event_id": prediction.registry_head_event_id,
                    "registry_head_event_sha256": prediction.registry_head_event_sha256,
                    "model_id": prediction.model_id,
                    "artifact_id": prediction.artifact_id,
                    "manifest_id": prediction.manifest_id,
                    "artifact_manifest_sha256": prediction.artifact_manifest_sha256,
                    "method": prediction.method,
                    "method_version": prediction.method_version,
                    "configuration_id": prediction.configuration_id,
                    "home_win_probability": prediction.probabilities.home_win,
                    "draw_probability": prediction.probabilities.draw,
                    "away_win_probability": prediction.probabilities.away_win,
                },
                identity_columns=("prediction_id",),
            )
        )
    return AggregateWritePlan(
        kind=AggregateKind.CURRENT_PREDICTIONS,
        identity=sha256_bytes(
            canonical_json_bytes(
                {
                    "prediction_ids": [
                        str(item.id) for item in sorted(predictions, key=lambda x: x.id)
                    ]
                }
            )
        ),
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(rows),
    )


def completed_evaluations_write_plan(
    evaluations: Sequence[CompletedPredictionEvaluation],
) -> AggregateWritePlan:
    """Build an immutable per-prediction completed-result evaluation aggregate."""

    if not evaluations:
        raise RepositoryContractError(
            "completed evaluation persistence cannot be empty"
        )
    if len({item.id for item in evaluations}) != len(evaluations):
        raise RepositoryContractError("completed evaluation repeats an identity")
    objects: dict[str, StoredObject] = {}
    rows: list[ImmutableRow] = []
    for evaluation in sorted(evaluations, key=lambda item: item.id):
        identity_payload = canonical_json_bytes(
            {
                "prediction_id": str(evaluation.prediction_id),
                "prediction_identity_sha256": evaluation.prediction_identity_sha256,
                "result_cache_key_sha256": evaluation.result_cache_key_sha256,
                "result_id": str(evaluation.result_id),
                "result_identity_sha256": evaluation.result_identity_sha256,
                "result_observation_id": str(evaluation.result_observation_id),
                "result_retrieved_at": evaluation.result_retrieved_at.isoformat(),
                "schema_version": evaluation.schema_version,
            }
        )
        identity_object = _canonical_object(
            identity_payload, format_id="prediction-completed-evaluation-identity-v1"
        )
        expected_id, expected_sha256, _ = completed_evaluation_identity(
            prediction_id=evaluation.prediction_id,
            prediction_identity_sha256=evaluation.prediction_identity_sha256,
            result_id=evaluation.result_id,
            result_identity_sha256=evaluation.result_identity_sha256,
            result_observation_id=evaluation.result_observation_id,
            result_cache_key_sha256=evaluation.result_cache_key_sha256,
            result_retrieved_at=evaluation.result_retrieved_at,
        )
        if (
            expected_id != evaluation.id
            or expected_sha256 != evaluation.identity_sha256
        ):
            raise RepositoryContractError("completed evaluation identity changed")
        evaluation_object = _canonical_object(
            canonical_json_bytes(evaluation),
            format_id="prediction-completed-evaluation-v1",
        )
        objects[identity_object.sha256] = identity_object
        objects[evaluation_object.sha256] = evaluation_object
        rows.append(
            ImmutableRow.build(
                PersistenceTable.COMPLETED_PREDICTION_EVALUATION,
                {
                    "evaluation_id": evaluation.id,
                    "identity_sha256": evaluation.identity_sha256,
                    "evaluation_object_sha256": evaluation_object.sha256,
                    "schema_version": evaluation.schema_version,
                    "prediction_id": evaluation.prediction_id,
                    "prediction_identity_sha256": (
                        evaluation.prediction_identity_sha256
                    ),
                    "result_id": evaluation.result_id,
                    "result_identity_sha256": evaluation.result_identity_sha256,
                    "result_observation_id": evaluation.result_observation_id,
                    "result_cache_key_sha256": evaluation.result_cache_key_sha256,
                    "result_retrieved_at": evaluation.result_retrieved_at,
                    "fixture_id": evaluation.fixture_id,
                    "season_id": evaluation.season_id,
                    "outcome": evaluation.outcome.value,
                    "actual_outcome_probability": evaluation.actual_outcome_probability,
                    "log_loss": evaluation.log_loss,
                    "multiclass_brier_score": evaluation.multiclass_brier_score,
                    "ranked_probability_score": evaluation.ranked_probability_score,
                },
                identity_columns=("evaluation_id",),
            )
        )
    return AggregateWritePlan(
        kind=AggregateKind.COMPLETED_PREDICTION_EVALUATIONS,
        identity=sha256_bytes(
            canonical_json_bytes(
                {
                    "evaluation_ids": [
                        str(item.id) for item in sorted(evaluations, key=lambda x: x.id)
                    ]
                }
            )
        ),
        objects=tuple(objects[key] for key in sorted(objects)),
        rows=tuple(rows),
    )


class PredictionLifecycleRepository:
    """Narrow façade preserving raw-manifest verification for lifecycle writes."""

    def __init__(self, repository: PostgresAggregateRepository) -> None:
        self._repository = repository

    def store_features(
        self,
        features: Sequence[UpcomingFeatureRow],
        *,
        opening_priors: Mapping[UUID, SeasonOpeningPrior],
        initial_elo_ratings: Mapping[UUID, float],
    ) -> PersistenceResult:
        return self._repository.persist(
            upcoming_features_write_plan(
                features,
                opening_priors=opening_priors,
                initial_elo_ratings=initial_elo_ratings,
            )
        )

    def store_predictions(
        self, predictions: Sequence[CurrentModelPrediction]
    ) -> PersistenceResult:
        return self._repository.persist(predictions_write_plan(predictions))

    def store_completed_evaluations(
        self, evaluations: Sequence[CompletedPredictionEvaluation]
    ) -> PersistenceResult:
        return self._repository.persist(completed_evaluations_write_plan(evaluations))
