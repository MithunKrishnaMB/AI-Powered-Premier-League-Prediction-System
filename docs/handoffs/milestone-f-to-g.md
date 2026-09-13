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
