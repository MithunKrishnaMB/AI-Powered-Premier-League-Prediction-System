# Milestone D to E Handoff

Milestone D's implementation is complete through Step 3.10. The platform now
has deterministic three-way benchmarks, fitted classifiers, score models,
chronological development evaluation, a sealed final-test identity, frozen
acceptance gates and global model-appropriate explanations.

The implementation is recorded in local commit `3ac10a2` (`complete milestone
D model acceptance and explanations`). This handoff closes Milestone D and
establishes Milestone E as the current milestone.

## Completed steps

- **3.1:** Deterministic reference-frequency naive and fixed-draw Elo
  three-way benchmarks on a chronological holdout.
- **3.2:** Deterministic L2-regularized multinomial logistic regression with
  training-window-only imputation and scaling.
- **3.3:** Five complete expanding-season walk-forward folds and aggregate log
  loss, multiclass Brier score and normalized RPS.
- **3.4:** Target-free, checksum-pinned 2025–26 untouched-test identity freeze.
- **3.5:** Three predefined deterministic CatBoost candidates, development-only
  selection and final in-memory development fit.
- **3.6:** Expanding prior-out-of-fold temperature-scaling assessment; identity
  calibration retained.
- **3.7:** Independent-Poisson team attack, defence and home-advantage score
  baseline with three-way projection.
- **3.8:** Training-window-only Dixon–Coles low-score correction.
- **3.9:** Frozen development acceptance gates with exact cross-method fixture
  identity validation and deterministic champion selection.
- **3.10:** Global model-appropriate explanation data for every evaluated model
  family.

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

## Verification at closeout

- Runtime: 64-bit Python 3.14.7.
- pytest: 265 passed.
- Branch-aware coverage: 91.28%, above the required 90%.
- Ruff formatting and lint: passed.
- Strict mypy: passed.
- Dependency check: passed with no broken requirements.
- Raw, canonical, feature and training verification remained current across all
  11 seasons and 4,180 fixtures.
- A second Step 3.9/3.10 assessment returned `already_current` with unchanged
  canonical bytes and the recorded checksum.
- No final-test prediction or metric was produced.

## Constraints carried into Milestone E

- Keep 2025–26 sealed until an explicitly authorized one-time final-test run.
- Enter data-dependent workflows through raw-manifest verification; never
  bypass the existing checksum chain.
- Preserve predictor/target separation and every point-in-time leakage boundary.
- Treat date-only fixtures on the same date as a simultaneous batch.
- Preserve canonical team UUIDs and fail unknown identities; never fuzzy-match.
- Betting-odds columns remain retained source data, not approved predictors.
- Preserve three explicit outcomes in order: home win, draw and away win.
- Preserve deterministic IDs, ordering, output bytes, checksums and complete
  historical provenance.
- Use chronological evaluation only; never randomly split the combined corpus.
- Keep strict typing and at least 90% branch coverage on Python 3.14.7.
- Do not add CI/CD configuration, databases, APIs, deployment or frontend work
  during Milestone E steps unless the roadmap and user scope explicitly reach
  them.

## Milestone E progress

- **4.1 complete:** deterministic version-1 artifact layout; strict classifier,
  preprocessing, calibration, absent-score-model, runtime, compatibility and
  provenance contracts; and distinct UUIDv5 model, component, artifact and
  manifest identities.
- **4.2 complete:** canonical, checksum-pinned CatBoost JSON and stateless
  preprocessor serialization, strict loading and all-development round-trip
  verification through the raw-manifest boundary.
- **4.3 complete:** append-only candidate and development-accepted registry
  events. Active promotion fails closed because no final-test evidence contract
  exists and no active model was created.
- **4.4 complete:** strict, immutable simulation fixtures, explicit scoreline
  distributions, sampled results, date-only batches, season inputs and table
  structures using canonical UUID identities.
- **4.5 complete:** stateless SHA-256 fixture draws and canonical inverse-CDF
  scoreline selection that is invariant to fixture iteration order.
- **4.6 complete:** ledger-reconciled table updates and official statistical
  tiebreak ordering, with a residual playoff requirement failing closed.

## Exact next step — 4.7

Vectorize 10,000 simulations over the established single-run structures. First
define the approved source and provenance for explicit fixture scoreline
distributions; the registered three-way classifier cannot supply them. Preserve
order-independent draws and fail closed on an unresolved official playoff. Do
not open 2025–26, add persistence or APIs or weaken canonical team identity,
point-in-time batches, predictor separation or raw-manifest verification.
