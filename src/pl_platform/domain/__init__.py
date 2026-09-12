"""Provider-independent football domain models."""

from pl_platform.domain.features import (
    FEATURE_ROW_SCHEMA_VERSION,
    CanonicalDatasetProvenance,
    PointInTimeFeatureRow,
    PredictorSet,
    PredictorValue,
    SourceArtifactProvenance,
    TrainingLabel,
    deterministic_feature_row_id,
)
from pl_platform.domain.fixtures import (
    Fixture,
    FixtureScore,
    FixtureStatistics,
    FixtureStatus,
    MatchOutcome,
    SourceFixtureReference,
    TeamMatchStatistics,
)
from pl_platform.domain.ratings import (
    ELO_SCHEMA_VERSION,
    EloMatchPrediction,
    EloParameters,
)
from pl_platform.domain.seasons import (
    PremierLeagueSeason,
    SeasonEntryStatus,
    SeasonRegistry,
    SeasonTeamMembership,
    load_season_registry,
)
from pl_platform.domain.teams import (
    CanonicalTeam,
    TeamRegistry,
    UnknownTeamAliasError,
    load_team_registry,
)
from pl_platform.domain.training import (
    TRAINING_ROW_SCHEMA_VERSION,
    TrainingExample,
    deterministic_training_example_id,
)

__all__ = [
    "ELO_SCHEMA_VERSION",
    "FEATURE_ROW_SCHEMA_VERSION",
    "TRAINING_ROW_SCHEMA_VERSION",
    "CanonicalDatasetProvenance",
    "CanonicalTeam",
    "EloMatchPrediction",
    "EloParameters",
    "Fixture",
    "FixtureScore",
    "FixtureStatistics",
    "FixtureStatus",
    "MatchOutcome",
    "PointInTimeFeatureRow",
    "PredictorSet",
    "PredictorValue",
    "PremierLeagueSeason",
    "SeasonEntryStatus",
    "SeasonRegistry",
    "SeasonTeamMembership",
    "SourceArtifactProvenance",
    "SourceFixtureReference",
    "TeamMatchStatistics",
    "TeamRegistry",
    "TrainingExample",
    "TrainingLabel",
    "UnknownTeamAliasError",
    "deterministic_feature_row_id",
    "deterministic_training_example_id",
    "load_season_registry",
    "load_team_registry",
]
