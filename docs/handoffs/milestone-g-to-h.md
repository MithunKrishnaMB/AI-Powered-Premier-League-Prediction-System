# Milestone G to H Handoff

## Completed boundary

Milestone G is complete through Step 6.9. It provides seven provider-neutral
capabilities; strict typed identities, time/status/score/field-governance
contracts; exact team, fixture and player resolution; safe transport and exact
immutable caching; idempotent fixture, result, standings and squad persistence;
and offline exact-byte recordings covering every capability.

The completed numbered steps are:

- 6.1: capability and provider-neutral domain contracts;
- 6.2: exact team and fixture transformation;
- 6.3: safe transport, authentication, quota and bounded retry policy;
- 6.4: immutable exact-byte provider caching;
- 6.5: idempotent fixture/status synchronization and simultaneous batches;
- 6.6: official completed-result reconciliation;
- 6.7: complete point-in-time standings synchronization;
- 6.8: reviewed players and complete squad snapshots; and
- 6.9: offline recorded-response contract replay for all seven capabilities.

The current schema head is `f0006_step_6_8`. Development and test databases
remain isolated. Historical raw-manifest verification is still mandatory for
every aggregate write. No production provider was selected or contacted and
the recordings contain only synthetic empty envelopes. Implementation commit
`f34c349` records Steps 6.5 through 6.9 and completes Milestone G.

## Closeout verification

- Runtime: 64-bit Python 3.14.7.
- pytest: 460 passed.
- Branch coverage: 90.50% (required minimum: 90%).
- Ruff lint and formatting: passed.
- Strict mypy: passed across 148 Python files.
- Dependency consistency, diff whitespace and local Markdown links: passed.
- PostgreSQL: version 18.4, restricted `pl_app`, UTC, isolated
  `pl_platform_dev` and `pl_platform_test` databases.
- Both databases are at exact head `f0006_step_6_8`; test downgrade/re-upgrade
  passed.
- Current-season database tests verified exact cache provenance, immutable
  projections, deferred constraints, idempotent retries and complete 20-team
  standings and squad populations.

## Preserved model and evaluation state

The 2025–26 target remains sealed and has never contributed to fitting, tuning,
calibration, acceptance or metrics. The development policy remains CatBoost
depth 6 with identity calibration and outcome order `home_win`, `draw`,
`away_win`. Development acceptance is not active promotion: no active model
exists. Three-way probabilities are not scoreline distributions. Simulation
remains exactly 10,000 runs with deterministic identities, seeds, dtypes and
complete position mass.

## Next boundary

Roadmap Step 7.1 is deterministic active-model loading. It may implement the
typed lookup, compatibility and artifact-loading boundary and verify success
with synthetic active-state fixtures. Against the actual registry it must fail
closed with a typed no-active result. Do not silently promote the
development-accepted artifact, inspect the sealed target or import the
production artifact corpus to manufacture a successful load.

Later Prediction Lifecycle work must preserve retrieval-time knowledge cutoffs,
simultaneous fixture batches, predictor/target separation, immutable
provenance, stable identities and chronological evaluation. APIs, deployment,
frontend and CI/CD remain outside this handoff.

The next task should begin with Step 7.1 only, first present a precise design
and implementation plan and wait for explicit approval before modifying files.

**Follow-on status:** Step 7.1 was subsequently approved and completed without
changing this handoff's preserved registry state. See the
[Step 7.1 to 7.2 handoff](step-7-1-to-7-2.md).
