# Milestone F to Milestone G Handoff

## Completed boundary

Milestone F is complete. PostgreSQL uses two isolated local databases through
the restricted `pl_app` role and the linear Alembic chain ends at
`f0004_step_5_7`. The schema covers every entity finalized in Step 5.1.

Steps 5.8 and 5.9 add a typed, raw-manifest-gated repository boundary and verify
it against the isolated test database. Writes preserve exact bytes and existing
UUID/SHA identities, run atomically in foreign-key order, force deferred checks
and reload-compare before commit. Identical retries are idempotent; conflicting
history, constraint failures and raw verification failures roll back or prevent
the transaction.

No production artifact corpus or simulation matrix has been imported. The
2025–26 target remains sealed, the registry remains
`development_accepted` with no active model and the CatBoost classifier has no
scoreline capability.

The Milestone F implementation is recorded by commit `22e595a`.

## Verification at closeout

- Runtime: 64-bit Python 3.14.7.
- Tests: 389 passed with 90.53% branch coverage.
- Ruff lint and formatting, strict mypy, dependency consistency, whitespace and
  local Markdown-link checks: passed.
- Database server: PostgreSQL 18.4, UTC, restricted `pl_app` login.
- Development and test targets: `f0004_step_5_7`, each with zero application
  rows after clean migration verification.
- Raw corpus: all 11 checksum-pinned captures verified before repository tests.
- Transaction coverage: atomic success, identical retry, existing-content
  conflict, later-row rollback, checksum rejection, immutable update rejection
  and pre-transaction raw-lineage rejection.
- Sealed boundary: no 2025–26 targets, scores or final-test metrics accessed.
- Registry boundary: no active model and no activation evidence created.
- Simulation boundary: no production distribution or matrix persisted and no
  scoreline distribution derived from CatBoost probabilities.

## Milestone F implementation map

- ER model:
  [PostgreSQL entity-relationship model](../architecture/postgresql-entity-relationship-model.md).
- Connections and Alembic:
  [PostgreSQL connections and Alembic](../architecture/postgresql-connections-and-alembic.md).
- Four-revision schema:
  [PostgreSQL migration chain](../architecture/postgresql-migrations.md).
- Repository and transaction boundary:
  [PostgreSQL repositories and transactions](../architecture/postgresql-repositories.md).
- Repository implementation:
  [repositories.py](../../src/pl_platform/persistence/repositories.py).
- Live transaction verification:
  [repository integration tests](../../tests/integration/persistence/test_repositories.py).

## Guarantees Milestone G must preserve

- Verify the reviewed raw manifest whenever historical lineage is consumed.
- Keep canonical fixture identities and explicit team aliases; never fuzzy
  match teams.
- Preserve point-in-time cutoffs and whole-date simultaneous batches for
  date-only fixtures.
- Keep retained betting-odds columns outside the approved predictor schema.
- Keep predictors, targets and provenance structurally separate.
- Preserve depth-6 CatBoost, identity calibration and outcome order
  `home_win`, `draw`, `away_win` until a separately reviewed model milestone.
- Do not turn development acceptance into active promotion or access final-test
  outcomes.
- Require explicit, independently identified scoreline distributions for
  simulation; never derive them from three-way classifier probabilities.
- Preserve deterministic identities, canonical bytes, checksums, compatibility
  pins, numerical dtypes and exactly 10,000 simulation runs.

## Exact next step — 6.1

Define current-provider capability and domain contracts. Specify the provider
operations, typed fixture/team payloads, identity and timestamp boundaries,
quota/error vocabulary and which fields are authoritative without implementing
an adapter or making network calls.

Do not implement fixture/team transformation (Step 6.2), retries and quota
handling (Step 6.3), response caching (Step 6.4), production artifact import,
final-test evaluation, active promotion, APIs, deployment, frontend code or
CI/CD configuration in Step 6.1.

Step 6.1 is now implemented by the provider-neutral contract documented in
[Current-Provider Capability and Domain Contracts](../data/current-provider-contracts.md).
The next boundary is recorded in the
[Step 6.1 to Step 6.2 handoff](step-6-1-to-6-2.md).
