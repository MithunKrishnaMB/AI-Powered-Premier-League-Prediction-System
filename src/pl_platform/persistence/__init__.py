"""PostgreSQL connection and immutable aggregate repositories."""

from pl_platform.persistence.current_squads import (
    CurrentSquadRepository,
    current_players_sync_plan,
    current_squad_sync_plan,
)
from pl_platform.persistence.current_sync import (
    CURRENT_SYNC_SCHEMA_VERSION,
    CurrentSeasonRepository,
    current_fixture_sync_plan,
    current_results_sync_plan,
    current_standings_sync_plan,
)
from pl_platform.persistence.database import (
    DatabaseConnectionError,
    DatabaseConnectionInfo,
    check_database_connection,
    create_database_engine,
)
from pl_platform.persistence.prediction import (
    PredictionLifecycleRepository,
    completed_evaluations_write_plan,
    predictions_write_plan,
    upcoming_features_write_plan,
)
from pl_platform.persistence.provider_cache import (
    ProviderCacheEntry,
    ProviderCacheRepository,
    provider_cache_write_plan,
)
from pl_platform.persistence.repositories import (
    AggregateKind,
    AggregateWritePlan,
    CanonicalizationProfile,
    FilesystemRawManifestVerifier,
    ImmutableRow,
    PersistenceFailureCategory,
    PersistenceResult,
    PersistenceTable,
    PostgresAggregateRepository,
    RawManifestEvidence,
    RawManifestVerificationError,
    RawManifestVerifier,
    RepositoryContractError,
    RepositoryError,
    StoredObject,
)

__all__ = [
    "CURRENT_SYNC_SCHEMA_VERSION",
    "AggregateKind",
    "AggregateWritePlan",
    "CanonicalizationProfile",
    "CurrentSeasonRepository",
    "CurrentSquadRepository",
    "DatabaseConnectionError",
    "DatabaseConnectionInfo",
    "FilesystemRawManifestVerifier",
    "ImmutableRow",
    "PersistenceFailureCategory",
    "PersistenceResult",
    "PersistenceTable",
    "PostgresAggregateRepository",
    "PredictionLifecycleRepository",
    "ProviderCacheEntry",
    "ProviderCacheRepository",
    "RawManifestEvidence",
    "RawManifestVerificationError",
    "RawManifestVerifier",
    "RepositoryContractError",
    "RepositoryError",
    "StoredObject",
    "check_database_connection",
    "completed_evaluations_write_plan",
    "create_database_engine",
    "current_fixture_sync_plan",
    "current_players_sync_plan",
    "current_results_sync_plan",
    "current_squad_sync_plan",
    "current_standings_sync_plan",
    "predictions_write_plan",
    "provider_cache_write_plan",
    "upcoming_features_write_plan",
]
