# Step 5.7 to Step 5.8 Handoff

## Completed boundary

The PostgreSQL ER model is now implemented through Alembic head
`f0004_step_5_7`. The four revisions cover exact bytes and identity, fixtures,
features and Elo, training/evaluation evidence, semantic models and artifacts,
append-only registry history, raw ingestion, explicit scoreline distributions,
simulation inputs/runs and complete aggregate summaries.

Both local databases use the restricted `pl_app` role. The test database was
verified through a full empty-to-head, head-to-base and empty-to-head cycle.
The development database should remain at head after local verification.

## Guarantees to preserve

- Import exact canonical JSON/JSONL/component bytes; never reconstruct them
  from normalized rows or `jsonb`.
- Verify the historical raw-data manifest before any artifact transaction.
- Supply and recompute existing UUIDv5/SHA-256 identities; never request
  database-generated identities.
- Preserve predictor/target separation and all point-in-time cutoff and
  simultaneous-batch boundaries.
- Keep the 2025–26 freeze target-free. No final-test evaluation is authorized.
- Keep classifier, preprocessing, calibration, score-model, physical component
  and registry records distinct.
- The selected policy remains depth-6 CatBoost with identity calibration and
  outcome order `home_win`, `draw`, `away_win`.
- Development acceptance is not active promotion; no active model exists.
- Scoreline distributions are explicit inputs and cannot be derived from the
  three-way CatBoost probabilities.
- Preserve exactly 10,000 simulations, unsigned deterministic seeds, exact
  `int64`/`int16`/`float64` components and complete position mass.

## Step 5.8 boundary

Implement typed repositories one aggregate at a time. Each repository should
validate the existing strict domain object and exact bytes before writing,
execute one atomic transaction, map named database failures to stable error
categories and reload/compare the stored aggregate before commit. Begin with
the low-level exact-object and identity/reference aggregates, then follow
foreign-key order through fixtures, features, training/evaluation, models and
registry and finally explicit simulation inputs and summaries.

Do not add current-provider ingestion, final-test evaluation, active promotion,
APIs, deployment, frontend code or CI/CD configuration in Step 5.8.
