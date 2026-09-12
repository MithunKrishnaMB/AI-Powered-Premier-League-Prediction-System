# Milestone D to E Handoff

Milestone D's implementation is complete through Step 3.10. The platform now
has deterministic three-way benchmarks, fitted classifiers, score models,
chronological development evaluation, a sealed final-test identity, frozen
acceptance gates and global model-appropriate explanations.

## Selected development policy

- Development seasons: 2015–16 through 2024–25.
- Comparable validation population: five complete expanding-season folds,
  2020–21 through 2024–25, containing 1,900 fixtures.
- Untouched test: all 380 fixtures from 2025–26; no target or test metric has
  been opened.
- Accepted methods: Elo, multinomial logistic, CatBoost, independent Poisson and
  Dixon–Coles.
- Champion: `catboost-depth6-regularized` with identity calibration.
- Champion development metrics: log loss 0.990106, Brier 0.588451 and RPS
  0.205650.

## Artifacts and entry point

Run `plp-assess-models` through the raw-manifest boundary. The canonical report
is
`data/processed/evaluation/epl/model-assessment-2015-2016_to_2024-2025/assessment-manifest.json`
with SHA-256
`15b86d54ba84f1df9737efafa9553d39022772a9cb9080cc2b30161bfcf2c7bc`.
It pins the complete training, base evaluation, CatBoost tuning, advanced
evaluation and test-freeze lineage.

## Step 4.1 boundary

Define a model artifact directory and manifest schema around the selected
development policy. Specify stable IDs, model/preprocessor components, runtime
requirements, checksums, training and evaluation lineage and compatibility
rules. Do not serialize models until Step 4.2, define promotion state transitions
until Step 4.3, simulate seasons, add persistence or APIs or open 2025–26.

Preserve canonical team UUIDs, predictor/target separation, point-in-time
cutoffs, simultaneous date-only batches, explicit three-way outcome ordering,
raw-manifest verification and byte-deterministic provenance.
