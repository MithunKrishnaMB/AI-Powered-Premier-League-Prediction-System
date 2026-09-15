"""Adversarial fail-closed coverage for the prediction lifecycle."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.evaluation.catboost_model import FittedCatBoostClassifier
from pl_platform.persistence.prediction import (
    completed_evaluations_write_plan,
    predictions_write_plan,
    upcoming_features_write_plan,
)
from pl_platform.persistence.repositories import RepositoryContractError
from pl_platform.prediction import (
    CompletedPredictionEvaluation,
    CompletedResultEvidence,
    CurrentFixtureEvidence,
    CurrentModelPrediction,
    PredictionLifecycleError,
    UpcomingFeatureRow,
    build_upcoming_feature_rows,
    evaluate_completed_prediction,
    generate_current_predictions,
)
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.prediction.test_lifecycle import _active_model, _feature


def test_current_evidence_rejects_invalid_time_state_and_date_only_cutoff() -> None:
    upcoming, completed, _, _, _ = feature_inputs()
    fixture_payload = upcoming.model_dump(mode="python")
    fixture_payload["retrieved_at"] = datetime(2026, 9, 15, 8)
    with pytest.raises(ValidationError, match="timestamps must be UTC"):
        CurrentFixtureEvidence.model_validate(fixture_payload)

    fixture_payload = upcoming.model_dump(mode="python")
    fixture_payload["retrieved_at"] = datetime(2026, 9, 15, 9, tzinfo=UTC)
    with pytest.raises(ValidationError, match="follow its knowledge boundary"):
        CurrentFixtureEvidence.model_validate(fixture_payload)

    fixture_payload = upcoming.model_dump(mode="python")
    fixture_payload["fixture"]["status"] = "postponed"
    with pytest.raises(ValidationError, match="scheduled fixture"):
        CurrentFixtureEvidence.model_validate(fixture_payload)

    fixture_payload = upcoming.model_dump(mode="python")
    fixture_payload["fixture"]["kickoff_precision"] = "date_only"
    with pytest.raises(ValidationError, match="whole-date batch"):
        CurrentFixtureEvidence.model_validate(fixture_payload)

    fixture_payload["batch_kind"] = "date_only_date"
    fixture_payload["knowledge_available_at"] = datetime(2026, 9, 20, 8, tzinfo=UTC)
    fixture_payload["retrieved_at"] = fixture_payload["knowledge_available_at"]
    with pytest.raises(ValidationError, match="precede its local date"):
        CurrentFixtureEvidence.model_validate(fixture_payload)

    result_payload = completed.model_dump(mode="python")
    result_payload["retrieved_at"] = datetime(2026, 8, 15, 17)
    with pytest.raises(ValidationError, match="retrieval must be UTC"):
        CompletedResultEvidence.model_validate(result_payload)

    result_payload = completed.model_dump(mode="python")
    result_payload["fixture"] = upcoming.fixture.model_dump(mode="python")
    with pytest.raises(ValidationError, match="official result"):
        CompletedResultEvidence.model_validate(result_payload)


def test_typed_records_recompute_every_deterministic_identity() -> None:
    feature, completed, _, _ = _feature()
    bad_feature = feature.model_dump(mode="python")
    bad_feature["identity_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="identity does not match"):
        UpcomingFeatureRow.model_validate(bad_feature)

    prediction = CurrentModelPrediction.model_construct(
        id=UUID(int=1),
        identity_sha256="1" * 64,
        feature_id=feature.id,
        feature_identity_sha256=feature.identity_sha256,
        fixture_id=feature.fixture_evidence.fixture.id,
        competition_id="eng-premier-league",
        season_id="2026-2027",
        home_team_id=feature.home_team_id,
        away_team_id=feature.away_team_id,
        kickoff_at=feature.kickoff_at,
        feature_cutoff_at=feature.feature_cutoff_at,
        registry_entry_id=UUID(int=2),
        registry_head_event_id=UUID(int=3),
        registry_head_event_sha256="2" * 64,
        model_id=UUID(int=4),
        artifact_id=UUID(int=5),
        manifest_id=UUID(int=6),
        artifact_manifest_sha256="3" * 64,
        configuration_id="catboost-depth6-regularized",
        probabilities=OutcomeProbabilities(home_win=0.5, draw=0.3, away_win=0.2),
    )
    with pytest.raises(ValidationError, match="identity does not match"):
        CurrentModelPrediction.model_validate(prediction.model_dump(mode="python"))

    del completed


def test_batch_and_scope_ambiguities_fail_before_feature_computation() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    second = upcoming.model_copy(
        update={
            "fixture": upcoming.fixture.model_copy(
                update={
                    "id": UUID(int=1010),
                    "home_team_id": upcoming.fixture.away_team_id,
                }
            ),
            "batch_id": UUID(int=6010),
            "batch_member_ordinal": 1,
        }
    )
    with pytest.raises(PredictionLifecycleError) as ambiguous:
        build_upcoming_feature_rows(
            fixtures=(upcoming, second),
            completed_results=(completed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert ambiguous.value.code == "chronology_violation"

    wrong_kind = upcoming.model_copy(update={"batch_kind": "date_only_date"})
    with pytest.raises(PredictionLifecycleError) as kind:
        build_upcoming_feature_rows(
            fixtures=(wrong_kind,),
            completed_results=(completed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert kind.value.code == "chronology_violation"

    wrong_scope = upcoming.model_copy(
        update={
            "fixture": upcoming.fixture.model_copy(update={"season_id": "2027-2028"})
        }
    )
    with pytest.raises(PredictionLifecycleError) as scope:
        build_upcoming_feature_rows(
            fixtures=(wrong_scope,),
            completed_results=(),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert scope.value.code == "invalid_feature_input"


def test_feature_inputs_require_population_provenance_and_unique_results() -> None:
    upcoming, completed, season, priors, ratings = feature_inputs()
    with pytest.raises(PredictionLifecycleError) as empty:
        build_upcoming_feature_rows(
            fixtures=(),
            completed_results=(),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert empty.value.code == "invalid_feature_input"

    with pytest.raises(PredictionLifecycleError) as duplicate:
        build_upcoming_feature_rows(
            fixtures=(upcoming,),
            completed_results=(completed, completed),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="6" * 64,
        )
    assert duplicate.value.code == "invalid_feature_input"

    with pytest.raises(PredictionLifecycleError) as membership:
        build_upcoming_feature_rows(
            fixtures=(upcoming,),
            completed_results=(completed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings={
                key: value
                for index, (key, value) in enumerate(ratings.items())
                if index
            },
            historical_context_sha256="6" * 64,
        )
    assert membership.value.code == "invalid_feature_input"

    with pytest.raises(PredictionLifecycleError) as provenance:
        build_upcoming_feature_rows(
            fixtures=(upcoming,),
            completed_results=(completed,),
            season=season,
            opening_priors=priors,
            initial_elo_ratings=ratings,
            historical_context_sha256="INVALID",
        )
    assert provenance.value.code == "provenance_mismatch"


def test_prediction_and_evaluation_fail_closed_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature, completed, _, _ = _feature()
    active = _active_model(tmp_path)
    with pytest.raises(PredictionLifecycleError) as empty:
        generate_current_predictions((), active)
    assert empty.value.code == "invalid_feature_input"

    wrong_schema = feature.model_copy(
        update={
            "predictors": feature.predictors.model_copy(update={"schema_id": "wrong"})
        }
    )
    with pytest.raises(PredictionLifecycleError) as schema:
        generate_current_predictions((wrong_schema,), active)
    assert schema.value.code == "predictor_schema_incompatible"

    prediction = generate_current_predictions((feature,), active)[0]
    official = completed.model_copy(
        update={
            "fixture": completed.fixture.model_copy(
                update={
                    "id": prediction.fixture_id,
                    "season_id": prediction.season_id,
                    "home_team_id": prediction.home_team_id,
                    "away_team_id": prediction.away_team_id,
                    "kickoff_at": prediction.kickoff_at,
                }
            ),
            "retrieved_at": datetime(2026, 9, 20, 17, tzinfo=UTC),
        }
    )
    evaluation = evaluate_completed_prediction(prediction, official)
    changed_metric = evaluation.model_dump(mode="python")
    changed_metric["log_loss"] = evaluation.log_loss + 1.0
    with pytest.raises(ValidationError, match="metric values do not match"):
        CompletedPredictionEvaluation.model_validate(changed_metric)

    sealed = prediction.model_copy(update={"season_id": "2025-2026"})
    with pytest.raises(PredictionLifecycleError) as sealed_error:
        evaluate_completed_prediction(sealed, official)
    assert sealed_error.value.code == "sealed_target_prohibited"

    premature = official.model_copy(
        update={"retrieved_at": prediction.feature_cutoff_at}
    )
    with pytest.raises(PredictionLifecycleError) as chronology:
        evaluate_completed_prediction(prediction, premature)
    assert chronology.value.code == "chronology_violation"

    def fail_prediction(self: object, predictors: object) -> object:
        del self, predictors
        raise ValueError("synthetic CatBoost failure")

    monkeypatch.setattr(
        FittedCatBoostClassifier, "predict_probabilities", fail_prediction
    )
    with pytest.raises(PredictionLifecycleError) as failed:
        generate_current_predictions((feature,), active)
    assert failed.value.code == "prediction_failed"


def test_persistence_plans_reject_empty_duplicate_and_changed_state() -> None:
    feature, _, priors, ratings = _feature()
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        upcoming_features_write_plan(
            (), opening_priors=priors, initial_elo_ratings=ratings
        )
    with pytest.raises(RepositoryContractError, match="repeats"):
        upcoming_features_write_plan(
            (feature, feature),
            opening_priors=priors,
            initial_elo_ratings=ratings,
        )
    changed_ratings = dict(ratings)
    changed_ratings[next(iter(changed_ratings))] += 1.0
    with pytest.raises(RepositoryContractError, match="checksums"):
        upcoming_features_write_plan(
            (feature,),
            opening_priors=priors,
            initial_elo_ratings=changed_ratings,
        )
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        predictions_write_plan(())
    with pytest.raises(RepositoryContractError, match="cannot be empty"):
        completed_evaluations_write_plan(())
