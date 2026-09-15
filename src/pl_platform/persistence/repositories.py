"""Typed, immutable and raw-manifest-gated PostgreSQL repositories."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Never, Protocol
from uuid import UUID

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from pl_platform.ingestion.download import DownloadError, verify_existing_file
from pl_platform.ingestion.manifest import load_manifest

MIGRATION_HEAD: Final = "f0007_step_7_4"
_IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_FORMAT_ID: Final = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")

type ScalarDatabaseValue = str | int | float | bool | bytes | UUID | date | datetime
type DatabaseValue = ScalarDatabaseValue | tuple[str, ...] | tuple[int, ...] | None


class PersistenceFailureCategory(StrEnum):
    """Stable application categories for persistence failures."""

    IDENTITY_MISMATCH = "identity_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NON_CANONICAL_BYTES = "non_canonical_bytes"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    CHRONOLOGY_VIOLATION = "chronology_violation"
    PREDICTOR_SCHEMA_INCOMPATIBLE = "predictor_schema_incompatible"
    OUTCOME_ORDER_INCOMPATIBLE = "outcome_order_incompatible"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    NUMERICAL_CONTRACT_MISMATCH = "numerical_contract_mismatch"
    INVALID_PROBABILITY_MASS = "invalid_probability_mass"
    REGISTRY_TRANSITION_INVALID = "registry_transition_invalid"
    FINAL_TEST_EVIDENCE_REQUIRED = "final_test_evidence_required"
    IMMUTABLE_RECORD_VIOLATION = "immutable_record_violation"
    EXISTING_RECORD_CONFLICT = "existing_record_conflict"
    SCHEMA_VERSION_INCOMPATIBLE = "schema_version_incompatible"
    RAW_MANIFEST_VERIFICATION_FAILED = "raw_manifest_verification_failed"
    DATABASE_CONSTRAINT_VIOLATION = "database_constraint_violation"
    DATABASE_OPERATION_FAILED = "database_operation_failed"


class AggregateKind(StrEnum):
    """Logical write boundaries supported by the repository."""

    EXACT_OBJECT = "exact_object"
    IDENTITY_REFERENCE = "identity_reference"
    RAW_CAPTURE = "raw_capture"
    CANONICAL_FIXTURES = "canonical_fixtures"
    FEATURES_ELO = "features_elo"
    TRAINING = "training"
    EVALUATION = "evaluation"
    MODEL_ARTIFACT = "model_artifact"
    REGISTRY = "registry"
    PROVIDER_CACHE = "provider_cache"
    CURRENT_FIXTURES = "current_fixtures"
    CURRENT_RESULTS = "current_results"
    CURRENT_STANDINGS = "current_standings"
    CURRENT_PLAYERS = "current_players"
    CURRENT_SQUADS = "current_squads"
    UPCOMING_FEATURES = "upcoming_features"
    CURRENT_PREDICTIONS = "current_predictions"
    COMPLETED_PREDICTION_EVALUATIONS = "completed_prediction_evaluations"
    SCORELINE_DISTRIBUTION = "scoreline_distribution"
    SIMULATION_INPUT = "simulation_input"
    SIMULATION_RUN = "simulation_run"
    SIMULATION_SUMMARY = "simulation_summary"


class PersistenceTable(StrEnum):
    """Allowlist of immutable relational projections at Step 5.7 head."""

    COMPETITION = "identity.competition"
    SOURCE = "identity.source"
    SOURCE_ALLOWED_HOST = "identity.source_allowed_host"
    REFERENCE_DOCUMENT = "identity.reference_document"
    TEAM = "identity.team"
    PLAYER = "identity.player"
    TEAM_REGISTRY_MEMBER = "identity.team_registry_member"
    TEAM_ALIAS = "identity.team_alias"
    SEASON = "identity.season"
    SEASON_REGISTRY_ENTRY = "identity.season_registry_entry"
    SEASON_MEMBERSHIP = "identity.season_membership"
    RAW_CAPTURE = "ingestion.raw_capture"
    CANONICAL_DATASET = "football.canonical_dataset"
    FIXTURE = "football.fixture"
    FIXTURE_REVISION = "football.fixture_revision"
    FIXTURE_SOURCE_REFERENCE = "football.fixture_source_reference"
    FIXTURE_BATCH = "football.fixture_batch"
    FIXTURE_BATCH_MEMBER = "football.fixture_batch_member"
    CURRENT_FIXTURE_SOURCE_REFERENCE = "football.current_fixture_source_reference"
    CURRENT_FIXTURE_REVISION = "football.current_fixture_revision"
    CURRENT_FIXTURE_OBSERVATION = "football.current_fixture_observation"
    CURRENT_FIXTURE_BATCH = "football.current_fixture_batch"
    CURRENT_FIXTURE_BATCH_PROVENANCE = "football.current_fixture_batch_provenance"
    CURRENT_FIXTURE_BATCH_MEMBER = "football.current_fixture_batch_member"
    CURRENT_COMPLETED_RESULT = "football.current_completed_result"
    CURRENT_RESULT_OBSERVATION = "football.current_result_observation"
    CURRENT_STANDING_SNAPSHOT = "football.current_standing_snapshot"
    CURRENT_STANDING_ROW = "football.current_standing_row"
    CURRENT_STANDING_SOURCE_REFERENCE = "football.current_standing_source_reference"
    CURRENT_PLAYER_SOURCE_REFERENCE = "football.current_player_source_reference"
    CURRENT_PLAYER_OBSERVATION = "football.current_player_observation"
    CURRENT_SQUAD = "football.current_squad"
    CURRENT_SQUAD_SOURCE_REFERENCE = "football.current_squad_source_reference"
    CURRENT_SQUAD_SNAPSHOT = "football.current_squad_snapshot"
    CURRENT_SQUAD_SNAPSHOT_PROVENANCE = "football.current_squad_snapshot_provenance"
    CURRENT_SQUAD_SNAPSHOT_TEAM = "football.current_squad_snapshot_team"
    CURRENT_SQUAD_MEMBER = "football.current_squad_member"
    PREDICTOR_SCHEMA = "feature.predictor_schema"
    PREDICTOR_DEFINITION = "feature.predictor_definition"
    PROCESSING_POLICY = "feature.processing_policy"
    FEATURE_DATASET = "feature.feature_dataset"
    FEATURE_ROW = "feature.feature_row"
    FEATURE_VALUE = "feature.feature_value"
    FEATURE_LABEL = "feature.feature_label"
    ELO_RATING_OBSERVATION = "feature.elo_rating_observation"
    TARGET_SCHEMA = "ml.target_schema"
    TRAINING_DATASET = "ml.training_dataset"
    TRAINING_DATASET_SEASON = "ml.training_dataset_season"
    TRAINING_FEATURE_SOURCE = "ml.training_feature_source"
    TRAINING_EXAMPLE = "ml.training_example"
    TRAINING_DATASET_EXAMPLE = "ml.training_dataset_example"
    TRAINING_TARGET = "ml.training_target"
    UNTOUCHED_TEST_FREEZE = "ml.untouched_test_freeze"
    UNTOUCHED_TEST_FREEZE_MEMBER = "ml.untouched_test_freeze_member"
    EVALUATION_DATASET = "ml.evaluation_dataset"
    EVALUATION_DATASET_SEASON = "ml.evaluation_dataset_season"
    EVALUATION_PARTITION = "ml.evaluation_partition"
    EVALUATION_PARTITION_SEASON = "ml.evaluation_partition_season"
    PROBABILISTIC_PREDICTION = "ml.probabilistic_prediction"
    EVALUATION_METRIC = "ml.evaluation_metric"
    CATBOOST_CANDIDATE = "ml.catboost_candidate"
    CATBOOST_FOLD_FIT = "ml.catboost_fold_fit"
    CALIBRATION_EVALUATION = "ml.calibration_evaluation"
    CALIBRATION_FOLD_FIT = "ml.calibration_fold_fit"
    SCORE_MODEL_EVALUATION = "ml.score_model_evaluation"
    POISSON_FIT = "ml.poisson_fit"
    DIXON_COLES_FIT = "ml.dixon_coles_fit"
    MODEL_ASSESSMENT = "ml.model_assessment"
    MODEL_ASSESSMENT_SOURCE = "ml.model_assessment_source"
    SEMANTIC_MODEL = "model.semantic_model"
    CLASSIFIER_SPECIFICATION = "model.classifier_specification"
    PREPROCESSING_SPECIFICATION = "model.preprocessing_specification"
    CALIBRATION_SPECIFICATION = "model.calibration_specification"
    SCORE_MODEL_SPECIFICATION = "model.score_model_specification"
    PREDICTION_CONTRACT = "model.prediction_contract"
    RUNTIME_REQUIREMENT = "model.runtime_requirement"
    MODEL_ARTIFACT = "model.model_artifact"
    ARTIFACT_MANIFEST = "model.artifact_manifest"
    ARTIFACT_COMPONENT = "model.artifact_component"
    REGISTRY_ENTRY = "registry.registry_entry"
    REGISTRY_EVENT = "registry.registry_event"
    PROVIDER_RESPONSE = "provider_cache.response"
    SCORELINE_DISTRIBUTION = "simulation.scoreline_distribution"
    SCORELINE_PROBABILITY = "simulation.scoreline_probability"
    DISTRIBUTION_PROVENANCE = "simulation.distribution_provenance"
    SIMULATION_INPUT = "simulation.simulation_input"
    SIMULATION_INPUT_TEAM = "simulation.simulation_input_team"
    SIMULATION_INPUT_COMPLETED_FIXTURE = "simulation.simulation_input_completed_fixture"
    SIMULATION_INPUT_BATCH = "simulation.simulation_input_batch"
    SIMULATION_INPUT_REMAINING_FIXTURE = "simulation.simulation_input_remaining_fixture"
    SIMULATION_RUN = "simulation.simulation_run"
    RESULT_COMPONENT = "simulation.result_component"
    SIMULATION_SUMMARY = "simulation.simulation_summary"
    TEAM_SUMMARY = "simulation.team_summary"
    POSITION_PROBABILITY = "simulation.position_probability"
    UPCOMING_FEATURE = "prediction.upcoming_feature"
    UPCOMING_FEATURE_RESULT_SOURCE = "prediction.upcoming_feature_result_source"
    UPCOMING_FEATURE_VALUE = "prediction.upcoming_feature_value"
    CURRENT_MODEL_PREDICTION = "prediction.current_model_prediction"
    COMPLETED_PREDICTION_EVALUATION = "prediction.completed_prediction_evaluation"


_TABLE_ORDER: Final = {table: ordinal for ordinal, table in enumerate(PersistenceTable)}
_KIND_TABLES: Final[dict[AggregateKind, frozenset[PersistenceTable]]] = {
    AggregateKind.EXACT_OBJECT: frozenset(),
    AggregateKind.IDENTITY_REFERENCE: frozenset(
        table for table in PersistenceTable if table.value.startswith("identity.")
    ),
    AggregateKind.RAW_CAPTURE: frozenset({PersistenceTable.RAW_CAPTURE}),
    AggregateKind.CANONICAL_FIXTURES: frozenset(
        table for table in PersistenceTable if table.value.startswith("football.")
    ),
    AggregateKind.FEATURES_ELO: frozenset(
        table for table in PersistenceTable if table.value.startswith("feature.")
    ),
    AggregateKind.TRAINING: frozenset(
        {
            PersistenceTable.TARGET_SCHEMA,
            PersistenceTable.TRAINING_DATASET,
            PersistenceTable.TRAINING_DATASET_SEASON,
            PersistenceTable.TRAINING_FEATURE_SOURCE,
            PersistenceTable.TRAINING_EXAMPLE,
            PersistenceTable.TRAINING_DATASET_EXAMPLE,
            PersistenceTable.TRAINING_TARGET,
            PersistenceTable.UNTOUCHED_TEST_FREEZE,
            PersistenceTable.UNTOUCHED_TEST_FREEZE_MEMBER,
        }
    ),
    AggregateKind.EVALUATION: frozenset(
        {
            PersistenceTable.EVALUATION_DATASET,
            PersistenceTable.EVALUATION_DATASET_SEASON,
            PersistenceTable.EVALUATION_PARTITION,
            PersistenceTable.EVALUATION_PARTITION_SEASON,
            PersistenceTable.PROBABILISTIC_PREDICTION,
            PersistenceTable.EVALUATION_METRIC,
            PersistenceTable.CATBOOST_CANDIDATE,
            PersistenceTable.CATBOOST_FOLD_FIT,
            PersistenceTable.CALIBRATION_EVALUATION,
            PersistenceTable.CALIBRATION_FOLD_FIT,
            PersistenceTable.SCORE_MODEL_EVALUATION,
            PersistenceTable.POISSON_FIT,
            PersistenceTable.DIXON_COLES_FIT,
            PersistenceTable.MODEL_ASSESSMENT,
            PersistenceTable.MODEL_ASSESSMENT_SOURCE,
        }
    ),
    AggregateKind.MODEL_ARTIFACT: frozenset(
        table for table in PersistenceTable if table.value.startswith("model.")
    ),
    AggregateKind.REGISTRY: frozenset(
        table for table in PersistenceTable if table.value.startswith("registry.")
    ),
    AggregateKind.PROVIDER_CACHE: frozenset({PersistenceTable.PROVIDER_RESPONSE}),
    AggregateKind.CURRENT_FIXTURES: frozenset(
        {
            PersistenceTable.FIXTURE,
            PersistenceTable.CURRENT_FIXTURE_SOURCE_REFERENCE,
            PersistenceTable.CURRENT_FIXTURE_REVISION,
            PersistenceTable.CURRENT_FIXTURE_OBSERVATION,
            PersistenceTable.CURRENT_FIXTURE_BATCH,
            PersistenceTable.CURRENT_FIXTURE_BATCH_PROVENANCE,
            PersistenceTable.CURRENT_FIXTURE_BATCH_MEMBER,
        }
    ),
    AggregateKind.CURRENT_RESULTS: frozenset(
        {
            PersistenceTable.FIXTURE,
            PersistenceTable.CURRENT_FIXTURE_SOURCE_REFERENCE,
            PersistenceTable.CURRENT_COMPLETED_RESULT,
            PersistenceTable.CURRENT_RESULT_OBSERVATION,
        }
    ),
    AggregateKind.CURRENT_STANDINGS: frozenset(
        {
            PersistenceTable.CURRENT_STANDING_SNAPSHOT,
            PersistenceTable.CURRENT_STANDING_ROW,
            PersistenceTable.CURRENT_STANDING_SOURCE_REFERENCE,
        }
    ),
    AggregateKind.CURRENT_PLAYERS: frozenset(
        {
            PersistenceTable.PLAYER,
            PersistenceTable.CURRENT_PLAYER_SOURCE_REFERENCE,
            PersistenceTable.CURRENT_PLAYER_OBSERVATION,
        }
    ),
    AggregateKind.CURRENT_SQUADS: frozenset(
        {
            PersistenceTable.CURRENT_SQUAD,
            PersistenceTable.CURRENT_SQUAD_SOURCE_REFERENCE,
            PersistenceTable.CURRENT_SQUAD_SNAPSHOT,
            PersistenceTable.CURRENT_SQUAD_SNAPSHOT_PROVENANCE,
            PersistenceTable.CURRENT_SQUAD_SNAPSHOT_TEAM,
            PersistenceTable.CURRENT_SQUAD_MEMBER,
        }
    ),
    AggregateKind.UPCOMING_FEATURES: frozenset(
        {
            PersistenceTable.UPCOMING_FEATURE,
            PersistenceTable.UPCOMING_FEATURE_RESULT_SOURCE,
            PersistenceTable.UPCOMING_FEATURE_VALUE,
        }
    ),
    AggregateKind.CURRENT_PREDICTIONS: frozenset(
        {PersistenceTable.CURRENT_MODEL_PREDICTION}
    ),
    AggregateKind.COMPLETED_PREDICTION_EVALUATIONS: frozenset(
        {PersistenceTable.COMPLETED_PREDICTION_EVALUATION}
    ),
    AggregateKind.SCORELINE_DISTRIBUTION: frozenset(
        {
            PersistenceTable.SCORELINE_DISTRIBUTION,
            PersistenceTable.SCORELINE_PROBABILITY,
            PersistenceTable.DISTRIBUTION_PROVENANCE,
        }
    ),
    AggregateKind.SIMULATION_INPUT: frozenset(
        {
            PersistenceTable.SIMULATION_INPUT,
            PersistenceTable.SIMULATION_INPUT_TEAM,
            PersistenceTable.SIMULATION_INPUT_COMPLETED_FIXTURE,
            PersistenceTable.SIMULATION_INPUT_BATCH,
            PersistenceTable.SIMULATION_INPUT_REMAINING_FIXTURE,
        }
    ),
    AggregateKind.SIMULATION_RUN: frozenset(
        {PersistenceTable.SIMULATION_RUN, PersistenceTable.RESULT_COMPONENT}
    ),
    AggregateKind.SIMULATION_SUMMARY: frozenset(
        {
            PersistenceTable.SIMULATION_SUMMARY,
            PersistenceTable.TEAM_SUMMARY,
            PersistenceTable.POSITION_PROBABILITY,
        }
    ),
}


class CanonicalizationProfile(StrEnum):
    OPAQUE = "opaque"
    CANONICAL_JSON = "canonical_json_v1"
    CANONICAL_JSONL = "canonical_jsonl_v1"
    IDENTITY_JSON = "identity_json_v1"
    NUMPY_ARRAY = "numpy_array_v1"


class RepositoryContractError(ValueError):
    """A write request is invalid before database access."""


class RawManifestVerificationError(RepositoryContractError):
    """The immutable raw corpus could not be verified."""


class RepositoryError(RuntimeError):
    """A stable, non-secret persistence failure."""

    def __init__(
        self,
        category: PersistenceFailureCategory,
        aggregate_kind: AggregateKind,
        *,
        constraint_name: str | None = None,
    ) -> None:
        self.category = category
        self.aggregate_kind = aggregate_kind
        self.constraint_name = constraint_name
        suffix = f" ({constraint_name})" if constraint_name else ""
        super().__init__(f"{aggregate_kind}: {category}{suffix}")


def _reject_json_constant(value: str) -> Never:
    raise RepositoryContractError(f"non-finite JSON constant is prohibited: {value}")


def _keys_are_sorted(value: object) -> bool:
    if isinstance(value, dict):
        keys = tuple(value)
        return keys == tuple(sorted(keys)) and all(
            _keys_are_sorted(child) for child in value.values()
        )
    if isinstance(value, list):
        return all(_keys_are_sorted(child) for child in value)
    return True


def _load_ordered_json(payload: str) -> object:
    value = json.loads(payload, parse_constant=_reject_json_constant)
    if not _keys_are_sorted(value):
        raise RepositoryContractError("canonical JSON object keys are not ordered")
    return value


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Authoritative exact bytes and their PostgreSQL content metadata."""

    sha256: str
    payload: bytes
    media_type: str
    encoding: str | None
    format_id: str
    canonicalization_profile: CanonicalizationProfile

    def __post_init__(self) -> None:
        actual = hashlib.sha256(self.payload).hexdigest()
        if not _SHA256.fullmatch(self.sha256) or actual != self.sha256:
            raise RepositoryContractError("stored-object checksum mismatch")
        if not self.payload:
            raise RepositoryContractError("stored-object payload cannot be empty")
        if not _FORMAT_ID.fullmatch(self.format_id):
            raise RepositoryContractError("stored-object format ID is invalid")
        profile = self.canonicalization_profile
        if profile is CanonicalizationProfile.NUMPY_ARRAY:
            if self.encoding is not None or self.media_type != "application/x-npy":
                raise RepositoryContractError("NumPy objects require binary metadata")
            return
        if profile is CanonicalizationProfile.OPAQUE:
            if self.encoding not in {"utf-8", "utf-8-sig", "cp1252"}:
                raise RepositoryContractError("opaque text encoding is unsupported")
            return
        if self.encoding != "utf-8" or self.payload.startswith(b"\xef\xbb\xbf"):
            raise RepositoryContractError("canonical JSON must be BOM-free UTF-8")
        try:
            decoded = self.payload.decode("utf-8")
            if profile is CanonicalizationProfile.CANONICAL_JSONL:
                if not decoded.endswith("\n") or "\r" in decoded:
                    raise RepositoryContractError(
                        "canonical JSON Lines requires LF termination"
                    )
                lines = decoded.removesuffix("\n").split("\n")
                if not lines or any(not line for line in lines):
                    raise RepositoryContractError("canonical JSON Lines is empty")
                for line in lines:
                    _load_ordered_json(line)
            else:
                if profile is CanonicalizationProfile.CANONICAL_JSON and (
                    not decoded.endswith("\n") or "\r" in decoded
                ):
                    raise RepositoryContractError(
                        "canonical JSON requires LF termination"
                    )
                _load_ordered_json(decoded)
        except UnicodeDecodeError as exc:
            raise RepositoryContractError("canonical JSON is not UTF-8") from exc

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        media_type: str,
        encoding: str | None,
        format_id: str,
        canonicalization_profile: CanonicalizationProfile,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        """Build an exact object while checking any externally declared digest."""

        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise RepositoryContractError("stored-object checksum mismatch")
        return cls(
            sha256=digest,
            payload=payload,
            media_type=media_type,
            encoding=encoding,
            format_id=format_id,
            canonicalization_profile=canonicalization_profile,
        )


@dataclass(frozen=True, slots=True)
class ColumnValue:
    name: str
    value: DatabaseValue

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise RepositoryContractError("database column name is invalid")


@dataclass(frozen=True, slots=True)
class ImmutableRow:
    """One exact normalized projection with an explicit lookup identity."""

    table: PersistenceTable
    values: tuple[ColumnValue, ...]
    identity_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.values)
        if not names or len(names) != len(set(names)):
            raise RepositoryContractError("row columns must be present and unique")
        if not self.identity_columns or len(self.identity_columns) != len(
            set(self.identity_columns)
        ):
            raise RepositoryContractError("row identity columns must be unique")
        if any(name not in names for name in self.identity_columns):
            raise RepositoryContractError("row identity is absent from its values")

    @classmethod
    def build(
        cls,
        table: PersistenceTable,
        values: Mapping[str, DatabaseValue],
        *,
        identity_columns: Sequence[str],
    ) -> ImmutableRow:
        return cls(
            table=table,
            values=tuple(ColumnValue(name, value) for name, value in values.items()),
            identity_columns=tuple(identity_columns),
        )


@dataclass(frozen=True, slots=True)
class AggregateWritePlan:
    """One domain aggregate written atomically in foreign-key order."""

    kind: AggregateKind
    identity: str
    objects: tuple[StoredObject, ...] = ()
    rows: tuple[ImmutableRow, ...] = ()

    def __post_init__(self) -> None:
        if not self.identity:
            raise RepositoryContractError("aggregate identity cannot be empty")
        unexpected = tuple(
            row.table for row in self.rows if row.table not in _KIND_TABLES[self.kind]
        )
        if unexpected:
            raise RepositoryContractError("row table is outside its aggregate boundary")
        digests = tuple(item.sha256 for item in self.objects)
        if len(digests) != len(set(digests)):
            raise RepositoryContractError("aggregate repeats a stored object")
        order = tuple(_TABLE_ORDER[row.table] for row in self.rows)
        if order != tuple(sorted(order)):
            raise RepositoryContractError("aggregate rows violate dependency order")
        identities = tuple(
            (
                row.table,
                tuple(
                    (name, repr(next(v.value for v in row.values if v.name == name)))
                    for name in row.identity_columns
                ),
            )
            for row in self.rows
        )
        if len(identities) != len(set(identities)):
            raise RepositoryContractError("aggregate repeats a row identity")
        if not self.objects and not self.rows:
            raise RepositoryContractError("aggregate write plan cannot be empty")


@dataclass(frozen=True, slots=True)
class RawManifestEvidence:
    manifest_sha256: str
    verified_artifacts: tuple[tuple[str, str], ...]

    @property
    def verified_artifact_ids(self) -> tuple[str, ...]:
        return tuple(identity for identity, _ in self.verified_artifacts)


class FilesystemRawManifestVerifier:
    """Verify every checksum-pinned raw capture before persistence begins."""

    def __init__(self, manifest_path: Path, data_root: Path) -> None:
        self._manifest_path = manifest_path
        self._data_root = data_root

    def verify(self) -> RawManifestEvidence:
        try:
            manifest_bytes = self._manifest_path.read_bytes()
            manifest = load_manifest(self._manifest_path)
            artifacts: list[tuple[str, str]] = []
            for entry in manifest.files:
                relative = PurePosixPath(entry.destination)
                path = self._data_root.joinpath(*relative.parts)
                verify_existing_file(entry, path)
                artifacts.append((entry.id, entry.sha256))
        except (DownloadError, OSError, ValueError) as exc:
            raise RawManifestVerificationError(
                "raw manifest verification failed before database access"
            ) from exc
        return RawManifestEvidence(
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            verified_artifacts=tuple(artifacts),
        )


class RawManifestVerifier(Protocol):
    """Structural contract for a pre-transaction raw verifier."""

    def verify(self) -> RawManifestEvidence: ...


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    aggregate_kind: AggregateKind
    aggregate_identity: str
    raw_manifest_sha256: str
    inserted_objects: int
    existing_objects: int
    inserted_rows: int
    existing_rows: int


def _quoted_table(table: PersistenceTable) -> str:
    schema, name = table.value.split(".", maxsplit=1)
    return f'"{schema}"."{name}"'


def _bind_value(value: DatabaseValue) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _comparable(value: object) -> object:
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, list):
        return tuple(value)
    return value


def _failure_category(
    constraint_name: str | None,
    primary_message: str,
) -> PersistenceFailureCategory:
    lowered = primary_message.casefold()
    for category in PersistenceFailureCategory:
        if lowered.startswith(f"{category.value}:"):
            return category
    name = (constraint_name or "").casefold()
    mappings = (
        ("deterministic_id", PersistenceFailureCategory.IDENTITY_MISMATCH),
        ("checksum", PersistenceFailureCategory.CHECKSUM_MISMATCH),
        ("canonical", PersistenceFailureCategory.NON_CANONICAL_BYTES),
        ("chronolog", PersistenceFailureCategory.CHRONOLOGY_VIOLATION),
        ("predictor", PersistenceFailureCategory.PREDICTOR_SCHEMA_INCOMPATIBLE),
        ("outcome_order", PersistenceFailureCategory.OUTCOME_ORDER_INCOMPATIBLE),
        ("runtime", PersistenceFailureCategory.RUNTIME_INCOMPATIBLE),
        ("probability", PersistenceFailureCategory.INVALID_PROBABILITY_MASS),
        ("registry", PersistenceFailureCategory.REGISTRY_TRANSITION_INVALID),
        (
            "final_test_evidence",
            PersistenceFailureCategory.FINAL_TEST_EVIDENCE_REQUIRED,
        ),
        ("immutable", PersistenceFailureCategory.IMMUTABLE_RECORD_VIOLATION),
        ("fk_", PersistenceFailureCategory.PROVENANCE_MISMATCH),
    )
    for marker, category in mappings:
        if marker in name:
            return category
    if constraint_name is None:
        return PersistenceFailureCategory.DATABASE_OPERATION_FAILED
    return PersistenceFailureCategory.DATABASE_CONSTRAINT_VIOLATION


class PostgresAggregateRepository:
    """Persist one immutable aggregate and verify it inside one transaction."""

    def __init__(
        self,
        engine: Engine,
        raw_manifest_verifier: RawManifestVerifier,
    ) -> None:
        self._engine = engine
        self._raw_manifest_verifier = raw_manifest_verifier

    def persist(self, plan: AggregateWritePlan) -> PersistenceResult:
        """Verify raw sources, atomically write, force checks and reload."""

        try:
            evidence = self._raw_manifest_verifier.verify()
        except RawManifestVerificationError as exc:
            raise RepositoryError(
                PersistenceFailureCategory.RAW_MANIFEST_VERIFICATION_FAILED,
                plan.kind,
            ) from exc
        self._verify_raw_lineage(plan, evidence)

        try:
            with self._engine.begin() as connection:
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
                )
                self._require_migration_head(connection, plan.kind)
                inserted_objects = sum(
                    self._store_object(connection, item) for item in plan.objects
                )
                inserted_rows = sum(
                    self._store_row(connection, row, plan.kind) for row in plan.rows
                )
                connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
                for item in plan.objects:
                    self._verify_object(connection, item, plan.kind)
                for row in plan.rows:
                    self._verify_row(connection, row, plan.kind)
        except RepositoryError:
            raise
        except SQLAlchemyError as exc:
            original = getattr(exc, "orig", None)
            diagnostic = getattr(original, "diag", None)
            constraint_name = getattr(diagnostic, "constraint_name", None)
            primary_message = str(getattr(diagnostic, "message_primary", ""))
            raise RepositoryError(
                _failure_category(constraint_name, primary_message),
                plan.kind,
                constraint_name=constraint_name,
            ) from exc

        return PersistenceResult(
            aggregate_kind=plan.kind,
            aggregate_identity=plan.identity,
            raw_manifest_sha256=evidence.manifest_sha256,
            inserted_objects=inserted_objects,
            existing_objects=len(plan.objects) - inserted_objects,
            inserted_rows=inserted_rows,
            existing_rows=len(plan.rows) - inserted_rows,
        )

    def get(
        self,
        table: PersistenceTable,
        identity: Mapping[str, DatabaseValue],
    ) -> Mapping[str, object] | None:
        """Read one immutable projection by its explicit application identity."""

        if not identity or any(not _IDENTIFIER.fullmatch(name) for name in identity):
            raise RepositoryContractError("read identity is invalid")
        clauses = " AND ".join(
            f'"{name}" IS NOT DISTINCT FROM :identity_{ordinal}'
            for ordinal, name in enumerate(identity)
        )
        parameters = {
            f"identity_{ordinal}": _bind_value(value)
            for ordinal, value in enumerate(identity.values())
        }
        statement = text(f"SELECT * FROM {_quoted_table(table)} WHERE {clauses}")
        try:
            with self._engine.connect() as connection:
                row = connection.execute(statement, parameters).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise RepositoryError(
                PersistenceFailureCategory.DATABASE_OPERATION_FAILED,
                AggregateKind.EXACT_OBJECT,
            ) from exc
        return None if row is None else MappingProxyType(dict(row))

    @staticmethod
    def _verify_raw_lineage(
        plan: AggregateWritePlan,
        evidence: RawManifestEvidence,
    ) -> None:
        artifact_sha256 = dict(evidence.verified_artifacts)
        for row in plan.rows:
            values = {item.name: item.value for item in row.values}
            manifest_sha256 = values.get("historical_manifest_sha256")
            if (
                manifest_sha256 is not None
                and manifest_sha256 != evidence.manifest_sha256
            ):
                raise RepositoryError(
                    PersistenceFailureCategory.PROVENANCE_MISMATCH,
                    plan.kind,
                )
            raw_artifact_id = values.get("raw_artifact_id")
            if raw_artifact_id is None and row.table is PersistenceTable.RAW_CAPTURE:
                raw_artifact_id = values.get("artifact_id")
            if raw_artifact_id is not None and (
                not isinstance(raw_artifact_id, str)
                or raw_artifact_id not in artifact_sha256
            ):
                raise RepositoryError(
                    PersistenceFailureCategory.PROVENANCE_MISMATCH,
                    plan.kind,
                )
            if (
                row.table is PersistenceTable.RAW_CAPTURE
                and isinstance(raw_artifact_id, str)
                and values.get("object_sha256") != artifact_sha256[raw_artifact_id]
            ):
                raise RepositoryError(
                    PersistenceFailureCategory.CHECKSUM_MISMATCH,
                    plan.kind,
                )

    @staticmethod
    def _require_migration_head(
        connection: Connection,
        kind: AggregateKind,
    ) -> None:
        revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one_or_none()
        if revision != MIGRATION_HEAD:
            raise RepositoryError(
                PersistenceFailureCategory.SCHEMA_VERSION_INCOMPATIBLE,
                kind,
            )

    @staticmethod
    def _store_object(connection: Connection, item: StoredObject) -> int:
        result = connection.execute(
            text(
                "INSERT INTO lineage.stored_object ("
                "sha256, byte_count, media_type, encoding, format_id, "
                "canonicalization_profile, payload) VALUES ("
                ":sha256, :byte_count, :media_type, :encoding, :format_id, "
                ":profile, :payload) ON CONFLICT DO NOTHING"
            ),
            {
                "sha256": item.sha256,
                "byte_count": len(item.payload),
                "media_type": item.media_type,
                "encoding": item.encoding,
                "format_id": item.format_id,
                "profile": item.canonicalization_profile.value,
                "payload": item.payload,
            },
        )
        return result.rowcount

    @staticmethod
    def _store_row(
        connection: Connection,
        row: ImmutableRow,
        kind: AggregateKind,
    ) -> int:
        columns = tuple(item.name for item in row.values)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join(f":value_{ordinal}" for ordinal in range(len(columns)))
        parameters = {
            f"value_{ordinal}": _bind_value(item.value)
            for ordinal, item in enumerate(row.values)
        }
        result = connection.execute(
            text(
                f"INSERT INTO {_quoted_table(row.table)} ({quoted_columns}) "
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            ),
            parameters,
        )
        if result.rowcount not in {0, 1}:
            raise RepositoryError(
                PersistenceFailureCategory.DATABASE_OPERATION_FAILED,
                kind,
            )
        return result.rowcount

    @staticmethod
    def _verify_object(
        connection: Connection,
        item: StoredObject,
        kind: AggregateKind,
    ) -> None:
        row = (
            connection.execute(
                text(
                    "SELECT byte_count, media_type, encoding, format_id, "
                    "canonicalization_profile, payload "
                    "FROM lineage.stored_object WHERE sha256 = :sha256"
                ),
                {"sha256": item.sha256},
            )
            .mappings()
            .one_or_none()
        )
        expected = {
            "byte_count": len(item.payload),
            "media_type": item.media_type,
            "encoding": item.encoding,
            "format_id": item.format_id,
            "canonicalization_profile": item.canonicalization_profile.value,
            "payload": item.payload,
        }
        if row is None or any(
            _comparable(row[name]) != _comparable(value)
            for name, value in expected.items()
        ):
            raise RepositoryError(
                PersistenceFailureCategory.EXISTING_RECORD_CONFLICT,
                kind,
            )

    @staticmethod
    def _verify_row(
        connection: Connection,
        row: ImmutableRow,
        kind: AggregateKind,
    ) -> None:
        value_by_name = {item.name: item.value for item in row.values}
        clauses = " AND ".join(
            f'"{name}" IS NOT DISTINCT FROM :identity_{ordinal}'
            for ordinal, name in enumerate(row.identity_columns)
        )
        parameters = {
            f"identity_{ordinal}": _bind_value(value_by_name[name])
            for ordinal, name in enumerate(row.identity_columns)
        }
        selected = (
            connection.execute(
                text(f"SELECT * FROM {_quoted_table(row.table)} WHERE {clauses}"),
                parameters,
            )
            .mappings()
            .one_or_none()
        )
        if selected is None or any(
            _comparable(selected[item.name]) != _comparable(item.value)
            for item in row.values
        ):
            raise RepositoryError(
                PersistenceFailureCategory.EXISTING_RECORD_CONFLICT,
                kind,
            )
