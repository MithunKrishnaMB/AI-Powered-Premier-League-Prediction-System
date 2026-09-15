"""Steps 7.3 and 7.4 prediction/evaluation contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from pl_platform.domain.evaluation import OutcomeProbabilities
from pl_platform.features.priors import SeasonOpeningPrior
from pl_platform.prediction import (
    CompletedResultEvidence,
    CurrentModelPrediction,
    PredictionLifecycleError,
    UpcomingFeatureRow,
    build_upcoming_feature_rows,
    evaluate_completed_prediction,
    generate_current_predictions,
)
from pl_platform.registry import (
    LoadedActiveModel,
    VerifiedRegistryEntry,
    canonical_json_bytes,
    load_current_active_model,
    sha256_bytes,
)
from pl_platform.registry.registry import (
    accept_development_candidate,
    load_registry_entry,
    register_model_artifact,
)
from tests.unit.prediction.helpers import feature_inputs
from tests.unit.registry.helpers import write_artifact


class SyntheticHistorySource:
    def __init__(self, entry: VerifiedRegistryEntry) -> None:
        self.entry = entry

    def load_entries(self, registry_root: Path) -> tuple[VerifiedRegistryEntry, ...]:
        del registry_root
        return (self.entry,)


def _active_model(tmp_path: Path) -> LoadedActiveModel:
    artifact_root = tmp_path / "artifacts"
    registry_root = tmp_path / "registry"
    manifest_path = write_artifact(artifact_root)
    registered = register_model_artifact(manifest_path, artifact_root, registry_root)
    accept_development_candidate(registered.entry_path, artifact_root)
    loaded = load_registry_entry(registered.entry_path)
    head = loaded.events[-1]
    snapshot = VerifiedRegistryEntry(
        entry_path=registered.entry_path,
        entry=loaded.entry,
        state="active",
        event_count=len(loaded.events),
        head_event_id=head.event_id,
        head_event_sha256=sha256_bytes(canonical_json_bytes(head)),
    )
    return load_current_active_model(
        registry_root=registry_root,
        artifact_root=artifact_root,
        history_source=SyntheticHistorySource(snapshot),
    )


def _feature() -> tuple[
    UpcomingFeatureRow,
    CompletedResultEvidence,
    dict[UUID, SeasonOpeningPrior],
    dict[UUID, float],
]:
    upcoming, completed, season, priors, ratings = feature_inputs()
    row = build_upcoming_feature_rows(
        fixtures=(upcoming,),
        completed_results=(completed,),
        season=season,
        opening_priors=priors,
        initial_elo_ratings=ratings,
        historical_context_sha256="6" * 64,
    )[0]
    return row, completed, priors, ratings


def test_synthetic_active_model_generates_deterministic_target_free_prediction(
    tmp_path: Path,
) -> None:
    feature, _, _, _ = _feature()
    active = _active_model(tmp_path)

    first = generate_current_predictions((feature,), active)
    second = generate_current_predictions((feature,), active)

    assert first == second
    prediction = first[0]
    assert prediction.configuration_id == "catboost-depth6-regularized"
    assert prediction.method == "catboost"
    assert prediction.probabilities.home_win + prediction.probabilities.draw + (
        prediction.probabilities.away_win
    ) == pytest.approx(1.0, abs=1e-12)
    assert not hasattr(prediction, "scorelines")


def test_prediction_requires_explicit_active_state(tmp_path: Path) -> None:
    feature, _, _, _ = _feature()
    active = _active_model(tmp_path)
    accepted = replace(
        active, registry=replace(active.registry, state="development_accepted")
    )

    with pytest.raises(PredictionLifecycleError) as error:
        generate_current_predictions((feature,), accepted)
    assert error.value.code == "active_model_required"


def test_completed_prediction_evaluation_uses_official_result_metrics(
    tmp_path: Path,
) -> None:
    feature, completed, _, _ = _feature()
    prediction = generate_current_predictions((feature,), _active_model(tmp_path))[0]
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

    assert evaluation.outcome == "home_win"
    assert evaluation.actual_outcome_probability == (prediction.probabilities.home_win)
    assert evaluation.log_loss >= 0.0
    assert evaluation.multiclass_brier_score >= 0.0
    assert evaluation.ranked_probability_score >= 0.0
    assert evaluate_completed_prediction(prediction, official) == evaluation


def test_completed_evaluation_rejects_mismatch_and_zero_actual_probability() -> None:
    feature, completed, _, _ = _feature()
    prediction_id = UUID(int=8001)
    # model_construct intentionally creates an isolated invalid numerical edge case.
    prediction = CurrentModelPrediction.model_construct(
        id=prediction_id,
        identity_sha256="7" * 64,
        feature_id=feature.id,
        feature_identity_sha256=feature.identity_sha256,
        fixture_id=completed.fixture.id,
        competition_id="eng-premier-league",
        season_id="2026-2027",
        home_team_id=completed.fixture.home_team_id,
        away_team_id=completed.fixture.away_team_id,
        kickoff_at=completed.fixture.kickoff_at,
        feature_cutoff_at=datetime(2026, 8, 14, tzinfo=UTC),
        registry_entry_id=UUID(int=1),
        registry_head_event_id=UUID(int=2),
        registry_head_event_sha256="8" * 64,
        model_id=UUID(int=3),
        artifact_id=UUID(int=4),
        manifest_id=UUID(int=5),
        artifact_manifest_sha256="9" * 64,
        configuration_id="catboost-depth6-regularized",
        probabilities=OutcomeProbabilities(home_win=0.0, draw=0.5, away_win=0.5),
    )
    with pytest.raises(PredictionLifecycleError) as zero:
        evaluate_completed_prediction(prediction, completed)
    assert zero.value.code == "zero_actual_probability"

    mismatch = completed.model_copy(
        update={"fixture": completed.fixture.model_copy(update={"id": UUID(int=99)})}
    )
    with pytest.raises(PredictionLifecycleError) as wrong:
        evaluate_completed_prediction(prediction, mismatch)
    assert wrong.value.code == "result_mismatch"
