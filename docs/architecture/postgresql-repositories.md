# PostgreSQL Repositories and Transactions

Steps 5.8 and 5.9 implement and verify the write boundary over Alembic head
`f0004_step_5_7`. They do not bulk-import the produced artifact corpus, evaluate
the sealed 2025–26 target, promote a model or configure a current provider.

## Typed write contract

`AggregateWritePlan` is a frozen transaction request containing:

- one explicit aggregate kind and application identity;
- zero or more exact `StoredObject` byte payloads; and
- zero or more allowlisted `ImmutableRow` relational projections with explicit
  lookup identities.

Every migrated application table belongs to exactly the intended aggregate
boundary. Rows must be supplied in the migration's foreign-key dependency
order and duplicate byte checksums or row identities are rejected before
database access. The repository never creates replacement surrogate IDs.

Exact objects preserve payload bytes, byte count, SHA-256, media type, encoding,
format identifier and canonicalization profile. Canonical JSON and JSON Lines
must be BOM-free UTF-8 with ordered object keys and finite JSON values; JSON
Lines additionally requires one LF-terminated object per line. NumPy objects
remain binary and distinct from JSON. Opaque raw text accepts only the reviewed
UTF-8, UTF-8-with-BOM and CP1252 encodings used by source manifests.

## Mandatory raw-data gate

`FilesystemRawManifestVerifier` loads the reviewed historical manifest and
calls the existing immutable-file verifier for every listed capture. It returns
the manifest checksum and each artifact/checksum pair only after all files
pass. This occurs before the repository asks the engine for a transaction.

Any `historical_manifest_sha256`, `raw_artifact_id` or raw-capture object
checksum included in a write plan must match that verified evidence. Missing,
unknown or conflicting lineage fails closed.

## Atomic transaction sequence

One repository write uses one serializable PostgreSQL transaction:

1. require exact Alembic head `f0004_step_5_7`;
2. insert authoritative exact objects;
3. insert normalized rows in dependency order;
4. force all deferred constraints to run;
5. reload and compare every exact object and supplied row value; and
6. commit only after all comparisons succeed.

Inserts use conflict-ignore solely to support identical retries. A conflict is
not success until the stored bytes, metadata and normalized values compare
exactly. Any mismatch produces `existing_record_conflict` and rolls the whole
transaction back.

Database exceptions are translated to stable categories for identity,
checksum, canonical-byte, provenance, chronology, predictor/outcome/runtime,
numerical/probability, registry, final-test, immutability and generic constraint
failures. Messages contain no database URL or credential.

## Step 5.9 verification

Unit tests cover canonical-byte profiles, checksum validation, aggregate/table
ownership, identity uniqueness, dependency ordering and complete raw-corpus
verification. Live integration tests use only `pl_platform_test` and cover:

- atomic exact-object plus normalized-row persistence;
- identical retry idempotency and reload;
- conflicting metadata under an existing checksum;
- rollback of an earlier exact-object insert after a later constraint failure;
- direct database checksum and immutable-update rejection; and
- raw-manifest rejection before any transaction can persist an object.

The tests preserve the current CatBoost depth-6, identity-calibration and
`home_win`, `draw`, `away_win` contracts already enforced by the migrations.
They do not read final-test targets, create an active registry event, derive a
scoreline distribution from classifier probabilities or persist production
simulation artifacts.
