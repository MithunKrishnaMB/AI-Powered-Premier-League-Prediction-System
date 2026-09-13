# Step 5.1 to 5.2 Handoff

## Completed step

Milestone F Step 5.1 is complete. The PostgreSQL entity-relationship model is
finalized against the exact data, manifests, model artifact, registry history
and simulation contracts produced through Milestone E.

Step 5.1 was intentionally documentation-only. It did not configure or connect
to PostgreSQL, initialize Alembic, create a migration or repository, persist a
simulation artifact, open the 2025–26 target or activate a model.

## Normative design

The complete design is
[PostgreSQL Entity-Relationship Model](../architecture/postgresql-entity-relationship-model.md).
ADR-030 records the lossless relational-projection decision.

The main boundaries are:

- existing UUIDv5 values, textual dataset IDs, SHA-256 checksums and
  owner-plus-ordinal composite keys remain primary identities;
- exact immutable bytes remain authoritative, with normalized relational rows
  used as checked query projections rather than reconstructed artifacts;
- raw captures, canonical datasets and fixture revisions, feature datasets,
  training datasets, evaluations, model manifests and components and registry
  events remain independently traceable;
- fixture identity is stable while dataset-owned revisions preserve changed
  kickoff or status observations without overwrite;
- predictors, feature labels and training targets remain structurally separate;
- classifier, preprocessing, calibration, score-model, artifact-component and
  registry metadata remain separate entities;
- the selected policy remains CatBoost depth 6 with identity calibration and
  fixed `home_win`, `draw`, `away_win` outcome order;
- registry state is derived from append-only checksum-linked events, and schema
  version 1 continues to reject active promotion;
- fixture scoreline distributions and their producer provenance are independent
  of the three-way classifier;
- simulation inputs preserve canonical team, fixture, distribution and batch
  order; version 1 remains fixed at 10,000 runs and its existing seed, identity,
  dtype and probability-mass contracts; and
- immutable provenance uses restrictive deletion, immediate local constraints
  and deferred cross-row constraints that fail closed.

## Preserved sealed boundaries

- The one-time 2025–26 final-test target remains unopened.
- The target-free freeze has no outcome, score or metric fields.
- Raw-data manifest verification remains the required entry to artifact import.
- Bookmaker fields retained by the source parser are not predictor-approved.
- Development evaluation remains chronological and never uses a random split.
- Development acceptance remains distinct from production activation; no active
  model exists.
- The CatBoost artifact cannot be cited as a scoreline-distribution producer.
- Python 3.14.7 and all exact predictor, library, runtime and numerical pins are
  unchanged.

## Exact next step — 5.2

Configure typed local and test PostgreSQL connections. Step 5.2 may add the
required database client dependency, environment settings, ignored local
configuration and a minimal connectivity check appropriate to the project's
strict typing and test policy.

Step 5.2 must not initialize Alembic, define migrations or tables, import
artifacts, implement repositories, persist simulations, access final-test
targets, promote an active model or add APIs, deployment, frontend or CI/CD
configuration. Alembic initialization remains Step 5.3 and schema creation
begins in Step 5.4.

## Step 5.1 verification

The documentation and source tree were checked for scope consistency. The full
local Python 3.14.7 quality results are recorded in `docs/project-status.md`.

