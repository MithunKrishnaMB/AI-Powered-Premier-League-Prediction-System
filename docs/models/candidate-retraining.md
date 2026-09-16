# Candidate Retraining

## Implemented boundary

Milestone J Step 9.5 is an explicit, in-memory model-training workflow. It is
not a scheduled task and creates no automation, CI/CD, GitHub Actions or DevOps
configuration. It does not write an artifact, append a registry event, compare
models, promote a candidate or generate predictions.

The workflow consumes four already verified inputs:

- a `RetrainingBaseline` derived from the exact canonical manifest of the
  accepted development artifact;
- the original 2015–16 through 2024–25 development examples only;
- immutable pre-match `UpcomingFeatureRow` values built before each operational
  fixture; and
- the corresponding official `CompletedResultEvidence` learned after kickoff.

`RetrainingBaseline.from_artifact` checks the exact manifest checksum and pins
the model, artifact, manifest, training-manifest and predictor-schema identities
plus the selected CatBoost depth-6 policy. It carries no registry state and
cannot reinterpret `development_accepted` as active.

## Target-safe operational examples

One operational training example is created only when the pre-match feature and
official result agree on canonical fixture, competition, season, teams and
kickoff. The feature predictors stay unchanged; the result score and outcome
are attached only as the structurally separate `TrainingLabel`. Result
retrieval must not precede kickoff.

Inputs must be complete one-to-one collections with unique fixture identities.
The workflow rejects partial pairing, duplicate baseline or operational
identities, predictor-schema drift, fixture overlap with historical training,
and operational seasons that do not follow the development window.

The 2025–26 season remains excluded. Its targets are neither accepted nor
loaded by this workflow. Current operational examples may begin with 2026–27,
and the exclusion is recorded in every candidate manifest.

## Candidate output

The combined examples are canonically ordered and refitted using the existing
deterministic CPU CatBoost contract: 200 trees, depth 6, learning rate 0.05, L2
regularization 10, seed 20260912, one thread, no bootstrap and identity
calibration policy. Returned diagnostics must exactly match that policy,
predictor schema and combined row count.

The result contains the fitted classifier in memory and a canonical
`candidate_unassessed` manifest. Its UUIDv5 identity and checksum bind:

- baseline model/artifact/manifest and source training-manifest checksums;
- exact baseline, operational and combined training checksums;
- canonical baseline, operational and excluded seasons;
- predictor schema and fixed CatBoost parameters;
- every operational feature/result/cache observation identity; and
- the latest official-result retrieval time as the knowledge cutoff.

The manifest deliberately contains no metric, comparison, promotion,
activation, registry-entry or scoreline-distribution field. The next roadmap
step may compare this unassessed candidate under a separately reviewed policy;
until then it has no registry or production meaning.
