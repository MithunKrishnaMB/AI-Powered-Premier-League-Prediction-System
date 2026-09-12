# Project Status

**Status date:** 2026-09-12

**Runtime:** 64-bit Python 3.14.7

**Completed milestones:** A — Repository Foundation; B — Historical Data System;
C — Point-in-Time Features and Elo

**Current milestone:** D — Probabilistic Models

**Completed Milestone D steps:** 3.1 — naive and Elo benchmarks; 3.2 —
multinomial logistic regression; 3.3 — expanding walk-forward validation; 3.4
— untouched test freeze; 3.5 — development-only CatBoost tuning

**Exact next step:** 3.6 — assess and apply probability calibration

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
- Raw, interim and processed files are reproducible local artifacts and are
  ignored by Git.

## Last verified quality result

The Steps 3.4 and 3.5 implementation passed the complete local suite:

- pytest: 211 passed.
- branch-aware coverage: 90.44% (minimum required: 90%).
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
- Probability calibration or score modelling.
- Model acceptance gates.
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
ranked probability score was 0.205650. These are development comparisons, not
final test performance.

## Next step boundary

Step 3.6 may assess calibration using only target-bearing predictions generated
inside the development walk-forward boundary. The frozen 2025–26 target remains
prohibited until an explicit one-time final-test evaluation step and cannot be
used for calibration choice, tuning, feature selection or acceptance design.
