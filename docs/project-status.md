# Project Status

**Status date:** 2026-09-12

**Runtime:** 64-bit Python 3.14.7

**Completed milestones:** A — Repository Foundation; B — Historical Data System;
C — Point-in-Time Features and Elo

**Current milestone:** D — Probabilistic Models; implementation complete and
awaiting the user-owned milestone commit

**Completed Milestone D steps:** 3.1 — naive and Elo benchmarks; 3.2 —
multinomial logistic regression; 3.3 — expanding walk-forward validation; 3.4
— untouched test freeze; 3.5 — development-only CatBoost tuning; 3.6 —
chronological calibration assessment; 3.7 — independent-Poisson score baseline;
3.8 — Dixon–Coles adjustment; 3.9 — frozen development acceptance gates; 3.10
— deterministic model-appropriate global explanations

**Exact next implementation step:** 4.1 — define artifact layout and manifest
schema, after Milestone D closeout

## Implemented capabilities

- Installable `pl_platform` package using the `src/` layout.
- Typed, immutable environment configuration.
- Structured JSON logging with recursive key-based secret redaction.
- Local Ruff, strict mypy, pytest, branch coverage and dependency checks.
- Versioned Football-Data manifest with HTTPS host allowlisting.
- Immutable, checksum-verified, idempotent historical downloads.
- Typed Football-Data row parsing with retained additional source fields.
- Provider-independent fixture, score, statistics, team and season contracts.
- Explicit canonical alias resolution for 34 clubs; no fuzzy identity matching.
- Reviewed membership and promotion metadata for 11 seasons.
- Dataset-wide double-round-robin and season-integrity checks.
- Deterministic JSON Lines materialization with companion lineage manifests.
- Batch `--all` and single-entry ingestion commands.
- Immutable, versioned point-in-time feature-row contract.
- Deterministic feature-row identity with canonical and raw-source lineage.
- Structural predictor/training-label separation and temporal boundary checks.
- Deterministic exact-kickoff and conservative whole-date fixture batches.
- Pre-batch snapshots with post-batch result and statistic updates.
- Season-to-date and five-match result, goal, shot, foul and card features.
- Missing-statistic observation counts without fabricated zero values.
- Rest, congestion, venue, promoted-team and season-progress context.
- Atomic, deterministic feature JSON Lines with companion lineage manifests.
- Single-season and all-season feature-materialization command.
- Explicit leakage, temporal, missing-data, checksum and idempotency tests.
- Explicit five-match-weighted season-opening priors with previous-team,
  previous-league and fixed-baseline source policies.
- Point-in-time Elo prediction and batch-delayed updates with reviewed
  initialization, home advantage and season transition constants.
- Recursive historical-context checksums binding cross-season predictors to
  every verified predecessor.
- Immutable, versioned training-example contract with separate predictors and
  result/score target.
- Deterministic all-season training-dataset materialization with typed loading
  and complete feature, canonical, raw, manifest and registry provenance.
- Strict target-free three-way probability and evaluation contracts.
- Reference-frequency naive and fixed-draw Elo benchmarks that preserve draws
  without misrepresenting Elo expected score as calibrated probabilities.
- Training-window-only mean imputation and standardization for every approved
  predictor in manifest order.
- Deterministic L2-regularized multinomial logistic regression using pinned
  NumPy float64 and no random initialization.
- Fixed 3,040-row reference and 760-row chronological holdout through 2024–25.
- Five complete-season expanding walk-forward folds from 2020–21 through
  2024–25, with 2025–26 excluded from all fitting and evaluation.
- Multiclass log loss, Brier score and normalized ranked probability score.
- Atomic target-free prediction artifacts and a typed manifest retaining the
  complete checksum and historical provenance chain.
- Formal target-free freeze of all 380 verified 2025–26 example identities,
  cutoffs and predictor checksums, with explicit test-access and development-use
  policies and no serialized outcomes or scores.
- Three predefined CatBoost candidates evaluated only in the five existing
  expanding development folds using deterministic, single-threaded CPU fits.
- Deterministic candidate selection by aggregate walk-forward log loss, then
  Brier score, ranked probability score and candidate ID; a final in-memory fit
  on all 3,800 development rows does not create a model artifact.
- Four expanding calibration assessments in which temperature is fit only on
  preceding CatBoost out-of-fold seasons and applied to the next complete
  season. Paired proper scores select the identity calibration policy.
- Deterministic independent-Poisson team attack, defence, intercept and home
  advantage fitting using only reference-window canonical team IDs and scores.
- A normalized 0–40 goal grid with expected goals bounded from 0.05 to 6.0 and
  three-way home-win, draw and away-win projection.
- Training-window-only Dixon–Coles rho fitting and low-score adjustment for
  0–0, 0–1, 1–0 and 1–1 without time weighting or test access.
- Atomic advanced-evaluation artifacts containing 5,320 target-free development
  predictions and strict training, CatBoost and untouched-test provenance.
- Frozen five-fold acceptance gates requiring identical complete coverage, at
  least 2% log-loss improvement over naive, no Brier or RPS regression and at
  least three fold-level log-loss wins.
- Deterministic accepted-champion selection by log loss, Brier, RPS and method
  ID; CatBoost is the development champion and identity calibration remains the
  selected policy.
- Global development-fit explanation data for naive frequencies, the Elo signal
  bridge, standardized multinomial coefficients, CatBoost
  `PredictionValuesChange`, canonical-team Poisson rate terms and Dixon–Coles
  rho and low-score scope.

## Historical dataset status

- Seasons: 2015–16 through 2025–26 inclusive.
- Completed-season source files: 11.
- Fixtures per season: 380.
- Total canonical fixtures: 4,180.
- Exact source kickoff timestamps: 2,660.
- Date-only source kickoffs: 1,520 across 2015–16 through 2018–19.
- Validated in-memory feature rows: 4,180.
- Materialized feature rows: 4,180.
- Predictor schema: `epl-pre-match` version 2 with 175 ordered predictors.
- Feature-row and feature-dataset schema versions: 2.
- Training rows: 4,180, with 380 from each of the 11 seasons.
- Training targets: 1,853 home wins; 1,337 away wins; 990 draws.
- Training row and dataset schema versions: 1.
- Training SHA-256:
  `d002097c5ccd471eb0987ffc505b544bfcad41e7c73b483f2110badc79054844`.
- Canonical dataset schema version: 2.
- Raw data location: `data/raw/football-data/epl/<season>/E0.csv`.
- Canonical location:
  `data/interim/canonical/epl/<season>/fixtures.jsonl`.
- Training location:
  `data/processed/training/epl/2015-2016_to_2025-2026/training.jsonl`.
- Development evaluation predictions: 7,980 target-free rows.
- Evaluation location:
  `data/processed/evaluation/epl/development-2015-2016_to_2024-2025/`.
- Evaluation predictions SHA-256:
  `793a75459ab0789a0001d29ab5d40526c9416da38572b482e19f60777a066ad0`.
- Evaluation manifest SHA-256:
  `8fb62a9306a4500a87f42bc0d4baacc9ba882231093014969f19d2fe151da08a`.
- Untouched test freeze rows: 380 from 2025–26.
- Untouched test identities SHA-256:
  `40f16d9067e96dc99db21703402ff5897043d4c59613b914eda71e3e8c5ab733`.
- Untouched test freeze manifest SHA-256:
  `56d2f74ae36b63b3cfdc22b54b771a386fff0ead614a40a03c47c449366eacba`.
- Selected CatBoost configuration: `catboost-depth6-regularized`.
- Selected CatBoost walk-forward predictions: 1,900 target-free rows.
- Selected CatBoost predictions SHA-256:
  `b9f878bdaf689082ce1216030fa9698378041d74cf6bd9a74435822345f39f46`.
- CatBoost tuning manifest SHA-256:
  `324039af347357582af5dc4d1c20c88b1e6dfbd0933402f30038d3902a08b7e3`.
- Advanced evaluation predictions: 5,320 target-free rows.
- Advanced evaluation location:
  `data/processed/evaluation/epl/advanced-development-2015-2016_to_2024-2025/`.
- Advanced predictions SHA-256:
  `786fab5892ec91feea5a19522d22b2cfb2027da608a770989d7387f60d9c8445`.
- Advanced manifest SHA-256:
  `2cb53b4925ef717c4a526e2b5f8960eac66f12bcd496e69ca37d8c618f55a4ab`.
- Model assessment location:
  `data/processed/evaluation/epl/model-assessment-2015-2016_to_2024-2025/`.
- Accepted development methods: Elo, multinomial logistic, CatBoost,
  independent Poisson and Dixon–Coles.
- Development champion: CatBoost with identity calibration.
- Model assessment manifest SHA-256:
  `15b86d54ba84f1df9737efafa9553d39022772a9cb9080cc2b30161bfcf2c7bc`.
- Raw, interim and processed files are reproducible local artifacts and are
  ignored by Git.

## Last verified quality result

The completed Milestone D implementation passed the complete local suite:

- pytest: 265 passed.
- branch-aware coverage: 91.28% (minimum required: 90%).
- Ruff lint: passed.
- Ruff format check: passed.
- strict mypy: passed.
- package dependency check: passed.
- raw manifest verification returned `already_present` for all 11 seasons.
- canonical materialization returned `already_current` for all 11 seasons.
- all 4,180 canonical fixtures produced feature rows; rebuilding from reversed
  input order produced identical serialized in-memory rows per season.
- predictor schema version 2 rebuilt all 11 season datasets with a recursive
  historical-context checksum and 175 predictors per row.
- the Step 2.8 training dataset was regenerated from all 4,180 verified feature
  rows with the recorded SHA-256.
- the final all-season feature and training rerun returned `already_current`
  throughout with unchanged checksums.
- typed artifact loading confirmed 760 fixed-prior team appearances in the first
  window and, in each later season, 646 previous-team plus 114
  previous-league team appearances.
- all six logistic fits converged under the frozen optimizer contract.
- an unchanged second model-evaluation run returned `already_current` with
  identical prediction and manifest checksums.
- the 2025–26 freeze contains only target-free identity, cutoff, predictor-hash
  and lineage data and is invariant to target changes.
- all 15 CatBoost fold fits used only seasons through 2024–25; the selected
  candidate was then fit in memory on all 3,800 development examples.
- a second freeze-and-tuning run returned `already_current` with identical
  prediction, tuning-manifest and freeze-manifest checksums.
- all calibration fits used only earlier out-of-fold development seasons; the
  paired 1,520-row assessment selected identity over temperature scaling.
- all Poisson and Dixon–Coles fold fits used only complete preceding seasons;
  the final in-memory fits used 3,800 development rows and never 2025–26.
- the advanced prediction artifact contains no targets, scores or test-season
  prediction rows and retains all three explicit outcome probabilities.
- a second advanced-evaluation run returned `already_current` with unchanged
  prediction and manifest checksums.
- acceptance validation confirmed that every candidate uses the same five fold
  identities and 1,900 rows as naive before applying any threshold.
- all five candidates passed the frozen gates; CatBoost was selected by the
  declared proper-score ordering with identity calibration.
- explanation-only fits used all 3,800 development rows and emitted no fixture
  targets, test predictions, model binaries or registry state.
- a second model-assessment run returned `already_current` with manifest SHA-256
  `15b86d54ba84f1df9737efafa9553d39022772a9cb9080cc2b30161bfcf2c7bc`.

## Important project constraints

- Do not add GitHub Actions, YAML-based CI/CD or other CI/CD automation unless
  the user explicitly changes this decision.
- Use Python 3.14.7 and preserve the declared `>=3.14,<3.15` support window.
- Keep secrets in ignored local environment files; never commit `.env`.
- Raw provider files are immutable and ignored by Git.
- Never overwrite conflicting raw data. A provider correction requires a
  reviewed manifest change or a separately identified capture.
- Canonical team mappings are explicit. Unknown aliases must fail rather than be
  fuzzy-matched.
- Store canonical timestamps in UTC after interpreting Football-Data timestamps
  in `Europe/London`.
- Treat `date_only` fixtures on the same date as a simultaneous batch during
  point-in-time feature updates.
- Retained bookmaker columns are not automatically eligible model features.
- Preserve a strict separation between predictors, labels and provenance to
  prevent target leakage.
- Develop the backend and ML system before the frontend.

## Not implemented yet

- Final one-time untouched-test evaluation.
- Model serialization or registry behavior.
- Season simulation.
- PostgreSQL persistence or migrations.
- Current-season provider integration.
- FastAPI endpoints.
- Deployment or frontend code.

## Development evaluation snapshot

The fixed 2023–24 through 2024–25 holdout produced log loss of 1.067476 for the
naive benchmark, 0.987353 for Elo and 1.002758 for multinomial logistic
regression. Across five expanding folds covering 1,900 validation matches, log
loss was 1.068916, 0.996658 and 1.033894 respectively. CatBoost candidate log
losses were 0.991213 (depth 4), 0.995511 (depth 5) and 0.990106 (selected depth
6). The selected candidate's aggregate Brier score was 0.588451 and normalized
ranked probability score was 0.205650. On the paired four-season calibration
window, uncalibrated CatBoost log loss was 0.975195 versus 0.978567 after
temperature scaling, so identity was selected. Across all five folds, Poisson
log loss was 1.010365 and Dixon–Coles log loss was 1.011675. These are
development comparisons, not final test performance.

## Next step boundary

Step 4.1 may define registry artifact layout and manifest schema around the
selected development champion. It must not serialize or promote a model yet,
open the one-time 2025–26 test target or weaken the immutable source and
evaluation lineage. Registry state transitions and promotion rules remain Step
4.3 work.
