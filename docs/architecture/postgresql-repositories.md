# PostgreSQL Repositories and Transactions

Steps 5.8 and 5.9 implement and verify the write boundary, now extended through
Alembic head `f0009_step_7_9`. They do not bulk-import the produced artifact
corpus, evaluate the sealed 2025–26 target, promote a model or configure a
current provider.

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

1. require exact Alembic head `f0009_step_7_9`;
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

## Step 6.4 provider cache

`ProviderCacheRepository` projects one validated `ProviderResponseCapture` into
two exact stored objects and one immutable `provider_cache.response` row. The
credential-free request identity uses `identity_json_v1`; the unmodified
provider body uses `opaque`; SHA-256 remains the identity of each byte stream.
The response object's format ID pins contract, provider-API and parser-schema
compatibility.

Writes use the same raw-manifest verifier, serializable transaction, migration
head check, conflict comparison and rollback behavior as every other aggregate.
An identical retry is idempotent, while different metadata under an existing
checksum or cache identity fails closed. Latest-fresh reads use exact source,
broad cache capability and request checksum, reject expired rows, reload both
byte streams and revalidate request operation, source, compatibility, media
metadata, checksums and deterministic cache key.

Step 9.1 extends the read side without changing the schema. `lookup_latest`
uses a read-only transaction at exact migration head and returns a validated
`fresh`, `stale` or `miss` state for the latest exact request known by the
lookup instant. The compatibility checks apply to stale entries as well, so
corrupt evidence cannot be disguised as a cache miss or provider refresh.
`get_latest_fresh` remains as the backward-compatible fresh-only projection.

Steps 9.2 and 9.3 reuse that same lookup and do not introduce a repository or
migration variant. The fixture polling job synchronizes only after a complete
read. Final-result reconciliation completes all exact-cache pages and canonical
identity checks before one `CurrentSeasonRepository.reconcile_results` call.
Consequently the historical raw-manifest verifier still runs before every
normalized write, while an empty result set opens no write transaction.

## Steps 6.5–6.7 current-season writes

`CurrentSeasonRepository` exposes three narrow operations over the same
raw-manifest-gated aggregate writer. Fixture synchronization writes stable
canonical fixtures, exact provider-reference mappings, content-derived fact
revisions, per-cache observations and validated batches. Completed-result
reconciliation writes one immutable official score per fixture plus any number
of identical-result response observations. Standings synchronization writes one
complete 20-row snapshot and separate provider-team references.

The plan builders preserve canonical table and member ordering and create
identity JSON objects for fixture revisions, fixture batches, results and
standings. Their SHA-256 values bind UUIDv5 identities. Exact provider request
and response bytes are not copied: restrictive cache foreign keys retain their
checksums, retrieval time and pinned compatibility metadata without weakening
the authoritative byte record.

PostgreSQL repeats the application validation at transaction end. It rejects
conflicting provider fixture mappings, out-of-order or regressive state,
incomplete date-only batches, results without a valid prior fixture state,
conflicting final scores and standings that differ from results known by the
snapshot retrieval instant. Conflict-ignore remains retry plumbing only;
reloaded rows must still compare exactly.

## Step 6.8 current player and squad writes

`CurrentSquadRepository` exposes separate player-resolution and complete-squad
operations. Player writes add reviewed canonical UUIDs, exact source references
and response observations. Squad writes add stable competition/season/team
squad UUIDs and one content-derived snapshot with UUID-ordered teams, active
memberships and every distinct cache key as provenance.

Both operations use the common raw-manifest-gated serializable writer. Deferred
database checks require cached metadata responses from the same source, prevent
unobserved or post-cutoff players, enforce exactly the 20 reviewed season teams
and validate registration and loan chronology. Exact response bytes remain in
the provider cache and are never replaced by normalized rows.

## Steps 7.2–7.4 prediction lifecycle writes

`PredictionLifecycleRepository` exposes three separate immutable aggregates:
upcoming features, active-model predictions and completed-result evaluations.
Every operation still passes through the historical raw-manifest verifier before
opening a serializable transaction.

Feature writes preserve canonical identity, row, predictor, completed-state,
opening-prior and initial-Elo bytes and normalize all 175 ordered values plus
every official result observation used. Prediction writes preserve canonical
bytes and exact feature, latest-active-registry-event, model, artifact and
manifest snapshots. Evaluation writes preserve canonical bytes and exact
prediction/result-observation lineage. Identical retries reload and compare;
changed bytes under an existing deterministic identity fail as conflicts.

Deferred constraints reject incomplete predictor populations, post-cutoff
results, non-active or stale registry events, mismatched official outcomes and
incorrect natural-log loss, Brier or normalized RPS values. The frozen
2025–26 season is rejected at all three boundaries.

## Steps 7.5–7.7 post-match writes

`PredictionOperationsRepository` exposes atomic state advancement, prediction
regeneration and simulation regeneration writes. State writes preserve exact
pre/post snapshot and advancement bytes, all 20 ordered Elo ratings and every
official result/evaluation relationship. Identical retries reload and compare;
unique result, evaluation and predecessor constraints reject double application
or state forks.

Prediction regeneration writes replacement feature/prediction aggregates and
their supersession records in one transaction. Simulation regeneration writes
independently approved explicit distributions, provenance, canonical input,
six deterministic NumPy arrays, aggregate summary and prior/replacement run
lineage. All three operations retain the historical raw-manifest gate. No write
updates prior state, feature, prediction, evaluation or simulation rows and no
repository converts three-way CatBoost probabilities into scorelines.

## Steps 7.8–7.9 post-match workflow journal

`PostMatchWorkflowRepository` stores one canonical manifest followed by a
fixed six-event checkpoint chain: planned, evaluations persisted, state
advancement persisted, predictions regenerated, simulation regenerated and
completed. Each event pins the prior event identity and the manifest-selected
child lineage checksum. Progress is always derived from the complete immutable
prefix; there is no mutable status or current-workflow pointer.

The runner invokes the existing exact-byte child repositories before appending
the corresponding checkpoint. If a child succeeds and acknowledgement is
lost, its identical retry is reloaded and compared. If an event commits and
acknowledgement is lost, recovery observes that event and starts at the next
stage. Gaps, reordered events, altered payloads and manifest conflicts fail
closed. The manifest, every event and both identity payloads remain canonical
stored objects behind the historical raw-manifest gate.
