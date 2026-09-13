# PostgreSQL Migration Chain

Steps 5.4 through 5.7 implement the finalized entity-relationship model as one
linear, transactional Alembic chain. The revisions contain schema only: they do
not import existing files, persist simulation matrices, evaluate the sealed
2025–26 target or promote a model.

| Revision | Step | Owned structures |
| --- | --- | --- |
| `f0001_step_5_4` | 5.4 | PostgreSQL domains and extensions; exact stored bytes; competition, source, reference, team and season identity; canonical fixture datasets, revisions and simultaneous batches |
| `f0002_step_5_5` | 5.5 | Ordered predictor schemas; processing/Elo contracts; feature rows, values and labels; distinct semantic-model, classifier, preprocessing, calibration, score-model and runtime metadata; artifact components; append-only registry events |
| `f0003_step_5_6` | 5.6 | Training datasets and targets; target-free 2025–26 freeze membership; chronological partitions, predictions and metrics; CatBoost candidates; calibration and score-model evaluations; accepted development assessment |
| `f0004_step_5_7` | 5.7 | Verified raw captures; future provider-cache responses; explicit scoreline distributions and provenance; canonical simulation inputs and batches; 10,000-run result components; complete aggregate summaries |

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
Step 5.8 must import aggregates through typed repositories, verify raw manifests
before opening writes and compare exact bytes and normalized relationships
before commit. Step 5.9 adds transaction-level negative tests; it does not
weaken the constraints already installed here.
