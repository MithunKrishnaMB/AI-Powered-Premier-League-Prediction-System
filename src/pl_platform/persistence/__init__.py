"""PostgreSQL connection and immutable aggregate repositories."""

from pl_platform.persistence.database import (
    DatabaseConnectionError,
    DatabaseConnectionInfo,
    check_database_connection,
    create_database_engine,
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
    "AggregateKind",
    "AggregateWritePlan",
    "CanonicalizationProfile",
    "DatabaseConnectionError",
    "DatabaseConnectionInfo",
    "FilesystemRawManifestVerifier",
    "ImmutableRow",
    "PersistenceFailureCategory",
    "PersistenceResult",
    "PersistenceTable",
    "PostgresAggregateRepository",
    "RawManifestEvidence",
    "RawManifestVerificationError",
    "RawManifestVerifier",
    "RepositoryContractError",
    "RepositoryError",
    "StoredObject",
    "check_database_connection",
    "create_database_engine",
]
