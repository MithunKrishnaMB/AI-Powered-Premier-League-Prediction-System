# PostgreSQL Migration Chain

Steps 5.4 through 10.5 implement the reviewed entity-relationship model as one
linear, transactional Alembic chain. The revisions contain schema only: they do
not import existing files, persist simulation matrices, evaluate the sealed
2025–26 target or promote a model.

| Revision | Step | Owned structures |
| --- | --- | --- |
| `f0001_step_5_4` | 5.4 | PostgreSQL domains and extensions; exact stored bytes; competition, source, reference, team and season identity; canonical fixture datasets, revisions and simultaneous batches |
| `f0002_step_5_5` | 5.5 | Ordered predictor schemas; processing/Elo contracts; feature rows, values and labels; distinct semantic-model, classifier, preprocessing, calibration, score-model and runtime metadata; artifact components; append-only registry events |
| `f0003_step_5_6` | 5.6 | Training datasets and targets; target-free 2025–26 freeze membership; chronological partitions, predictions and metrics; CatBoost candidates; calibration and score-model evaluations; accepted development assessment |
| `f0004_step_5_7` | 5.7 | Verified raw captures; future provider-cache responses; explicit scoreline distributions and provenance; canonical simulation inputs and batches; 10,000-run result components; complete aggregate summaries |
| `f0005_step_6_7` | 6.5–6.7 | Current fixture references, content-derived revisions, cache-provenanced observations and batches; official completed-result ledger; complete reconciled standings; `abandoned` fixture persistence |
| `f0006_step_6_8` | 6.8 | Canonical players; exact player/squad source references; cache-provenanced player observations; canonical season/team squads; complete point-in-time squad snapshots, membership and loan chronology |
| `f0007_step_7_4` | 7.2–7.4 | Current-evidence upcoming features and ordered predictor values; active-head/model-bound immutable predictions; official-result-bound per-fixture probabilistic evaluations |
| `f0008_step_7_7` | 7.5–7.7 | Append-only operational result/Elo states; exactly-once batch advancement; immutable prediction and deterministic season-simulation regeneration lineage |
| `f0009_step_7_9` | 7.8–7.9 | Canonical post-match workflow manifests; hash-linked append-only stage checkpoints; deterministic retry and recovery state |
| `f0010_step_10_5` | 10.5 | Function-only repair of canonical-dataset validation to use the final `completed` season column; no table, data or privilege change |

Step 6.1 adds provider-neutral executable contracts only and introduces no
Alembic revision or database write. Its five operations map onto the existing
Step 5.7 cache vocabulary: teams use `metadata`, fixtures and fixture status use
`fixtures`, completed results use `results` and standings use `standings`.
Revision `f0005_step_6_7` adds `abandoned` to the score-free historical fixture
revision states before current synchronization may store it.

Step 6.4 uses the existing `lineage.stored_object` and
`provider_cache.response` structures and therefore adds no migration. Cache
writes retain exact request identity and response bytes as separate stored
objects and an immutable response row links their checksums to retrieval,
expiry and HTTP metadata.

Steps 6.5 through 6.7 add immutable current-season projections without changing
dataset-owned historical fixture revisions. Provider identifiers remain in
separate reference tables. Every normalized observation has a restrictive
foreign key to the exact cached response. Deferred triggers enforce chronology,
whole-local-date batching, completion consistency, full 20-team membership and
result-ledger reconciliation at the response retrieval boundary.

Step 6.8 keeps optional players and squads separate from required match
synchronization. It adds reviewed canonical player identities, exact provider
references, immutable observations and complete 20-team squad snapshots with
content-derived identity. Deferred validation checks source/cache provenance,
canonical ordering, season membership, retrieval-time knowledge, active
registration windows and loan parents. Step 6.9 adds only offline recordings
and executable contract tests, so it requires no migration.

Revision `f0007_step_7_4` adds a separate `prediction` schema. It preserves
current fixture and result facts through exact composite foreign keys, stores
canonical identity and record bytes, requires all 175 predictor values, requires
the referenced registry event to be the latest explicit `active` event and
recomputes completed-evaluation outcome probability, natural-log loss, Brier
score and normalized RPS. Every new table is immutable and rejects the frozen
2025–26 season.

Revision `f0008_step_7_7` extends that schema with immutable operational state,
state-result/rating projections, one-successor state advancements and
prior/replacement prediction and simulation lineage. Deferred validation
requires complete 20-team/ordered-result state, one-time result/evaluation
application, refreshed replacement features containing the applied results and
replacement simulation inputs containing those fixtures as completed. The
existing simulation tables now permit exact component-byte reuse across roles
while retaining role/shape/dtype validation.

Revision `f0009_step_7_9` adds immutable post-match workflow manifests and a
six-stage hash-linked event journal. Database constraints enforce the canonical
stage order, predecessor chain, manifest-selected lineage checksum and one
event per sequence/stage. No mutable completion flag or active pointer exists.

Revision `f0010_step_10_5` repairs the historical canonical-dataset validator
found by the first complete historical-to-API release transaction. The
original function referenced the superseded `is_complete` name even though the
final season schema uses `completed`. The replacement retains every fixture-
count, membership, round-robin, chronology and batch invariant and changes no
stored data, table or privilege.

The chain preserves application-supplied UUIDv5 and SHA-256 identities. Exact
canonical bytes remain authoritative in `lineage.stored_object`; relational
projections have explicit ordinals, restrictive foreign keys and immutable-row
guards. Deferred triggers validate cross-row completeness, registry event
history, date-only batching and probability conservation at transaction end.

Choose a target explicitly before running Alembic:

```powershell
$env:PLP_ENVIRONMENT = "test" # or development
alembic upgrade head
alembic current
```

For an empty disposable test database, the reviewed rollback check is:

```powershell
$env:PLP_ENVIRONMENT = "test"
alembic downgrade base
alembic upgrade head
```

Do not run `downgrade base` against a database containing retained artifacts.
Step 5.8 now supplies typed aggregate repositories that verify raw manifests
before opening writes and compare exact bytes and normalized relationships
before commit. Step 5.9 verifies transaction rollback, idempotency, conflicts,
checksums and immutable guards. Current-season and release integration tests
run against exact head `f0010_step_10_5`.

Step 10.1 converts the complete local cycle into an opt-in executable release
contract. `pytest --cov --require-local-release` first proves that the selected
connection is the restricted `pl_app` login on `pl_platform_test`, then uses an
externally supplied connection and caller-owned outer transaction to downgrade
head to base and upgrade each of the ten revisions in order. It checks the
version after every upgrade, requires all twelve bounded schemas at head and
rolls the outer transaction back so pre-existing test state is restored. The
development database is never supplied to Alembic and its head is compared
before and after the cycle.

The static migration test separately pins the exact file set, single head,
parent edge for every revision and absence of branch labels or dependency
edges. Together these checks reject an accidental branch, extra revision,
missing downgrade or silently skipped local database cycle.
