"""Current-season prediction lifecycle."""

from .domain import (
    COMPLETED_EVALUATION_SCHEMA_VERSION,
    CURRENT_PREDICTION_SCHEMA_VERSION,
    SEALED_TEST_SEASON_ID,
    UPCOMING_FEATURE_SCHEMA_VERSION,
    CompletedPredictionEvaluation,
    CompletedResultEvidence,
    CurrentFixtureEvidence,
    CurrentModelPrediction,
    PredictionLifecycleError,
    PredictionLifecycleFailureCode,
    UpcomingFeatureRow,
)
from .lifecycle import (
    build_upcoming_feature_rows,
    completed_state_bytes,
    evaluate_completed_prediction,
    generate_current_predictions,
    initial_elo_bytes,
    opening_priors_bytes,
)

__all__ = [
    "COMPLETED_EVALUATION_SCHEMA_VERSION",
    "CURRENT_PREDICTION_SCHEMA_VERSION",
    "SEALED_TEST_SEASON_ID",
    "UPCOMING_FEATURE_SCHEMA_VERSION",
    "CompletedPredictionEvaluation",
    "CompletedResultEvidence",
    "CurrentFixtureEvidence",
    "CurrentModelPrediction",
    "PredictionLifecycleError",
    "PredictionLifecycleFailureCode",
    "UpcomingFeatureRow",
    "build_upcoming_feature_rows",
    "completed_state_bytes",
    "evaluate_completed_prediction",
    "generate_current_predictions",
    "initial_elo_bytes",
    "opening_priors_bytes",
]
