# Milestone G to H Handoff

## Completed boundary

Milestone G is complete through Step 6.9. It provides seven provider-neutral
capabilities; strict typed identities, time/status/score/field-governance
contracts; exact team, fixture and player resolution; safe transport and exact
immutable caching; idempotent fixture, result, standings and squad persistence;
and offline exact-byte recordings covering every capability.

The current schema head is `f0006_step_6_8`. Development and test databases
remain isolated. Historical raw-manifest verification is still mandatory for
every aggregate write. No production provider was selected or contacted and
the recordings contain only synthetic empty envelopes.

## Preserved model and evaluation state

The 2025–26 target remains sealed and has never contributed to fitting, tuning,
calibration, acceptance or metrics. The development policy remains CatBoost
depth 6 with identity calibration and outcome order `home_win`, `draw`,
`away_win`. Development acceptance is not active promotion: no active model
exists. Three-way probabilities are not scoreline distributions. Simulation
remains exactly 10,000 runs with deterministic identities, seeds, dtypes and
complete position mass.

## Next boundary

Roadmap Step 7.1 is deterministic active-model loading, but it must fail closed
until a separately authorized and implemented final-test/promotion path creates
an active registry event. Do not silently promote the development-accepted
artifact or import the production artifact corpus to satisfy that prerequisite.

Later Prediction Lifecycle work must preserve retrieval-time knowledge cutoffs,
simultaneous fixture batches, predictor/target separation, immutable
provenance, stable identities and chronological evaluation. APIs, deployment,
frontend and CI/CD remain outside this handoff.
