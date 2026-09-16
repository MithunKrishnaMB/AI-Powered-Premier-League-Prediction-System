# Current-Season Fixture, Result and Standings Synchronization

## Implemented scope

Steps 6.5 through 6.7 persist provider-neutral current-season match knowledge
without importing the historical artifact corpus or choosing an external
provider. Every write still verifies the reviewed historical raw-data manifest
before opening its serializable transaction. The current response must already
exist in `provider_cache.response`; its exact request and response bytes remain
the authoritative evidence.

Historical `football.fixture_revision` remains owned by immutable canonical
datasets. Current observations therefore share only `football.fixture`, whose
UUIDv5 identity is still competition, season, home team and away team. Separate
current tables prevent provider observations from masquerading as a historical
dataset revision.

## Step 6.5 fixture state

One current fixture is represented by three distinct concepts:

- `current_fixture_source_reference` maps an exact provider fixture ID to one
  stable canonical fixture and rejects conflicting reuse;
- `current_fixture_revision` stores a content-derived, immutable fixture fact
  containing kickoff precision, source timezone/date, status and optional
  descriptive metadata; and
- `current_fixture_observation` records which exact cached response supplied
  that fact and when it became known.

Repeated exact captures are no-ops. A later capture of the same fact can add an
observation without duplicating the fact revision. Kickoff or status changes
produce another content-derived revision. Database checks reject out-of-order
backfills, decreasing provider update times, exact-to-date-only regressions and
state transitions out of cancelled or abandoned; an in-progress fixture may
remain in progress or become abandoned until official completion is reconciled
separately.

`transform_fixture_statuses` applies the required fixture-status capability
only to an exact, already-known provider fixture reference. It retains the
known kickoff/team fact, records provider observation/update times and rejects
unknown references or `finished` without the official result response. Status
polls add no partial schedule batch.

`current_fixture_batch` and its ordered members preserve chronology. Exact
fixtures batch only at the same UTC kickoff. If any fixture in the captured
provider-local date is date-only, every observed fixture on that date and in
the same response provenance set belongs to one UUID-ordered simultaneous
batch. Its feature cutoff is the instant before local midnight; its knowledge
boundary is the latest contributing response retrieval time.

The migration also adds `abandoned` to the historical fixture-revision status
and score-free state checks. It does not create historical abandoned rows.

## Step 6.6 completed results

`transform_completed_results` resolves both provider team IDs through the
reviewed `CurrentTeamResolution`, re-derives the canonical fixture UUID and
retains the full response capture. The official result ledger allows exactly
one score and matching `home_win`, `draw` or `away_win` outcome per canonical
fixture. A second observation of the same result retains its own cache
provenance; a different score for that fixture conflicts and fails closed.

A result observation requires a prior current fixture observation under the
same exact provider fixture reference. Cancelled and abandoned fixtures cannot
complete and an explicit completion time cannot precede the latest known
kickoff. The result retrieval time—not provider completion time—is the
point-in-time knowledge boundary. Result scores remain targets for their own
fixture and may affect predictor state only for later fixture batches.

Step 9.3 adds a cache-aware orchestration layer without changing this schema or
write plan. It classifies each exact completed-result request as fresh, stale
or missing, preserves exact-byte compatibility/retrieval/expiry provenance and
finishes every page before calling `reconcile_results` once. Duplicate fixture
identities, cursor cycles, incompatible cache evidence and unavailable provider
capability fail before a database write. Empty complete result sets are no-ops.

## Step 6.7 standings

`transform_current_standings` requires positions 1 through 20 exactly once,
the complete reviewed season membership and exact provider-team resolution.
Every row independently checks played, result and goal-difference arithmetic,
including an explicit points adjustment.

Before persistence, `reconcile_standings_with_results` compares each row with
official results whose response retrieval is no later than the standings
retrieval. A deferred PostgreSQL trigger repeats this reconciliation against
the persisted ledger and requires all 20 rows and 20 separate provider-team
references. Provider position is retained as authoritative reconciliation
data; standings are not added to the approved 175-predictor schema.

## Preserved boundaries

Provider identifiers remain separate from canonical competition, season, team
and fixture identities. No fuzzy matching path exists. All foreign keys are
restrictive and all new rows are immutable. UUID and SHA-256 identities,
canonical ordering, exact cached bytes, retrieval timestamps and compatibility
metadata preserve complete provenance.

These steps do not ingest squads or players, access the sealed 2025–26 target,
import production artifacts, change chronological evaluation, activate a
model, infer scorelines from CatBoost probabilities, alter 10,000-run
simulation behavior, add an API, deploy, create frontend code or configure
CI/CD. Betting odds remain retained-only exact response data and are never
projected into a predictor table.
