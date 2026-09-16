# Retraining observability and manual operations

Step 9.7 provides a passive, deterministic operational snapshot and this
manual runbook. It does not provide a scheduler, monitor loop, notification
service, CI/CD workflow, GitHub Action, deployment configuration or DevOps
substitute.

## Current operational truth

- The filesystem registry state is `development_accepted`.
- The active-model count is zero.
- Production remains fail closed because no production database or current-
  data provider is configured.
- Candidate retraining and comparison are explicit in-memory calls.
- No candidate artifact or registry entry is produced by Milestone J.
- The sealed 2025–26 target and one-time final-test evidence remain unavailable.

## Passive snapshot

`build_retraining_operational_snapshot` accepts a canonical comparison report,
its exact SHA-256 checksum and an explicit UTC observation time. It performs no
I/O and captures only the current supported state:

- `registry_state: development_accepted`;
- `active_model_count: 0`;
- the comparison report/candidate identities and decision;
- one decision-specific signal; and
- `execution_mode: explicit_manual_only`.

The decision signal is `comparison_evidence_incomplete` for insufficient
evidence, `baseline_retained` when a gate fails or
`candidate_requires_human_review` when all gates pass. The latter is an action
for a person to review evidence, not an instruction that software can execute.
Every snapshot also states that the registry is unchanged and no automated
execution exists.

Snapshot construction fails if the report bytes do not match their checksum or
the observation time precedes the report's latest result knowledge. Snapshot
identity is derived from canonical content, so the same reviewed inputs yield
the same bytes and UUID.

## Manual review checklist

1. Re-verify the baseline artifact manifest and candidate manifest checksums.
2. Confirm every comparison feature cutoff is later than the candidate
   knowledge cutoff and every result is official and post-kickoff.
3. Confirm the population contains no candidate-training fixture and excludes
   2025–26.
4. Confirm population size, three-outcome coverage and both classifiers'
   predictor schema.
5. Review log loss first, followed by Brier and ranked probability score.
6. Record the canonical report and passive snapshot outside the production
   artifact corpus if an operator needs an audit copy.
7. Leave the registry unchanged. Active promotion still requires a separately
   approved typed final-test evidence contract and implementation.

## Failure response

- `candidate_incompatible`: discard the comparison attempt and reconstruct the
  candidate from the exact verified baseline inputs.
- `sealed_target_prohibited`: stop immediately; do not inspect or transform the
  target.
- `chronology_violation` or `training_overlap`: rebuild a genuinely later,
  disjoint holdout.
- `feature_result_mismatch` or `duplicate_identity`: repair evidence selection;
  do not partially score it.
- `predictor_schema_incompatible`: use the exact artifact predictor schema;
  never coerce or reorder predictors silently.
- `prediction_failed`: retain the baseline and diagnose the classifier using
  sanitized local evidence only.

These actions remain manual. Adding recurring execution, alerts, deployment or
provider/runtime composition requires separate explicit approval.
