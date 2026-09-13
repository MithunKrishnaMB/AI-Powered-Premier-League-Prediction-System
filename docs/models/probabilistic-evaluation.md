# Probabilistic Development Evaluation

## Scope

Steps 3.1 through 3.10 implement deterministic naive and Elo benchmarks, an
L2-regularized multinomial logistic baseline, expanding-season walk-forward
validation, a formal untouched-test freeze, bounded CatBoost tuning,
chronological calibration assessment, Poisson and Dixon–Coles score models,
frozen development acceptance gates and global model-appropriate explanations.
They do not implement a final untouched-test evaluation, model registry or
serving.

Every production evaluation begins by invoking the existing training
materializer. Raw files are therefore rechecked against the tracked historical
manifest before canonical, feature and training checksums are accepted.

## Chronological windows

The fixed holdout trains on 2015–16 through 2022–23 (3,040 matches) and evaluates
2023–24 plus 2024–25 (760 matches). Five expanding folds train on every complete
prior development season and evaluate, respectively, 2020–21, 2021–22, 2022–23,
2023–24 and 2024–25. Every fold contains 380 evaluation fixtures. The 2025–26
season is frozen and excluded from every development fit, prediction and metric.

Season-level boundaries preserve point-in-time ordering and cannot split a
date-only simultaneous fixture batch. Within each partition, rows retain their
feature cutoff, kickoff and deterministic identity ordering.

## Benchmark contracts

The naive benchmark is the empirical `home_win`, `draw`, `away_win`
distribution from that partition's reference seasons. It is frozen before any
evaluation prediction.

The Elo benchmark reads only `home_elo_expected_score` and
`away_elo_expected_score` from predictor schema `epl-pre-match` version 2. The
values must be finite complementary floats. Given reference draw rate `d` and
home expected score `e`, it emits:

```text
P(draw) = d
P(home_win) = (1 - d) * e
P(away_win) = 1 - P(draw) - P(home_win)
```

This uses Elo only as the relative non-draw strength signal. It is not described
or evaluated as an already calibrated three-way forecast.

## Multinomial logistic contract

The model consumes all 175 approved predictors in their manifest-pinned order.
Training-window preprocessing converts booleans to zero/one, mean-imputes
missing values, maps an entirely missing training column to zero and standardizes
with population variance. Constant columns use scale one. Evaluation values
never influence these statistics.

The three-class softmax model starts with zero coefficients and reference class
frequency intercepts. It uses L2 strength 1.0 and deterministic full-batch Adam:
learning rate 0.02, beta values 0.9 and 0.999, epsilon `1e-8`, relative objective
tolerance `2e-7`, patience eight and at most 1,200 iterations. All supported
partitions must converge. Computation uses pinned NumPy 2.5.3 float64 and no
random state.

Weights are intentionally kept in memory. Model serialization and registry
semantics belong to later milestones.

## Untouched test contract

The 2025–26 season is frozen as `untouched-test-2025-2026-v1`. Its manifest pins
the complete verified 380-example membership and upstream training lineage by
hashing only target-free identity, time boundary, source and predictor data. It
does not read or serialize outcomes, scores or test-label aggregates.

The contract prohibits target access until an explicit one-time final-test
evaluation. It also prohibits the season from influencing training, tuning,
selection, calibration or acceptance design. This is a freeze, not a test run;
there is currently no 2025–26 performance result.

## CatBoost tuning contract

CatBoost 1.2.10 consumes the same 175 approved predictors in manifest order.
Three candidates are fixed in code before evaluation:

| Candidate | Trees | Depth | Learning rate | L2 leaf regularization |
| --- | ---: | ---: | ---: | ---: |
| `catboost-depth4-conservative` | 200 | 4 | 0.03 | 3 |
| `catboost-depth5-conservative` | 300 | 5 | 0.03 | 5 |
| `catboost-depth6-regularized` | 200 | 6 | 0.05 | 10 |

Every candidate is scored on the same five expanding folds. Selection minimizes
aggregate natural-log loss, then Brier score, normalized ranked probability
score and candidate ID. Fits use CPU, one thread, seed 20260912, no bootstrap,
zero random strength, symmetric trees, `Min` NaN handling and no CatBoost file
writes. The selected depth-6 candidate is finally fit in memory on all 3,800
development examples. No model binary is persisted.

The aggregate development results are:

| Candidate | Log loss | Brier | RPS |
| --- | ---: | ---: | ---: |
| depth 4 | 0.991213 | 0.589204 | 0.205971 |
| depth 5 | 0.995511 | 0.591666 | 0.206621 |
| depth 6 (selected) | 0.990106 | 0.588451 | 0.205650 |

These are walk-forward development results, not final test performance.

## Calibration assessment

Temperature scaling raises each CatBoost probability to `1 / temperature` and
renormalizes the three outcomes. The scalar is constrained to `[0.25, 4.0]` and
fit with a deterministic 96-iteration golden-section search minimizing natural
log loss.

The first CatBoost out-of-fold season, 2020–21, supplies calibration history but
is not scored as calibrated. For each season from 2021–22 through 2024–25, the
temperature is fit only on all preceding out-of-fold seasons and then applied to
the next whole season. This produces a paired 1,520-match assessment without
using the prediction's own target or splitting a simultaneous date batch.

Temperature scaling produced log loss 0.978567, Brier score 0.581670 and RPS
0.201827, compared with 0.975195, 0.579316 and 0.200545 for the same uncalibrated
CatBoost rows. The selection rule therefore retains identity calibration. A
final development-only diagnostic fit over all 1,900 out-of-fold rows found
temperature 1.124308, but it is not adopted or serialized.

## Independent-Poisson score baseline

The baseline fits a global intercept, home advantage and canonical-team attack
and defence coefficients on each reference window. It models home and away
goals as conditionally independent Poisson variables:

```text
log(lambda_home) = intercept + home_advantage + attack_home + defence_away
log(lambda_away) = intercept + attack_away + defence_home
```

Coefficients use L2 strength 0.01 and deterministic 2,000-iteration full-batch
Adam with learning rate 0.03, beta values 0.9 and 0.999 and epsilon `1e-8`.
Expected goals are bounded to `[0.05, 6.0]`. A promoted team unseen in the
reference window receives neutral zero attack and defence coefficients rather
than a guessed identity. The normalized score grid covers 0 through 40 goals
for each team and projects to home win, draw and away win. Score grids remain in
memory; the evaluation artifact stores only target-free three-way projections.

Across the five 1,900-match development folds, log loss was 1.010365, Brier
score 0.603093 and RPS 0.214432.

## Dixon–Coles adjustment

The adjustment fits one rho value using only the same reference rows as the
underlying Poisson model. A deterministic scalar likelihood search is bounded
to `[-0.15, 0.025]`, which keeps all correction factors positive under the
expected-goal cap. It changes only the four low-score cells:

```text
tau(0, 0) = 1 - lambda_home * lambda_away * rho
tau(0, 1) = 1 + lambda_home * rho
tau(1, 0) = 1 + lambda_away * rho
tau(1, 1) = 1 - rho
```

No time decay or joint parameter refit is introduced in this baseline. The
final development diagnostic rho was -0.027104. Across the five folds, the
adjusted projection produced log loss 1.011675, Brier score 0.603583 and RPS
0.214514, so it did not improve this independent-Poisson baseline.

## Frozen development acceptance

Step 3.9 compares Elo, multinomial logistic, the selected CatBoost identity
policy, independent Poisson and Dixon–Coles against naive on the identical five
complete folds and 1,900 predictions. A candidate is accepted only when it:

- covers the same folds, fixtures and outcome counts as naive;
- improves aggregate natural-log loss by at least 2%;
- has aggregate Brier score and RPS no worse than naive; and
- beats naive log loss in at least three of five folds.

The champion is the accepted candidate with minimum aggregate log loss, then
Brier, RPS and method ID. All five candidates pass. CatBoost has the best
development log loss at 0.990106 and is selected. Temperature scaling is not a
separate candidate because its paired assessment covers only four folds; the
selected identity policy supplies CatBoost's complete five-fold result.

This is a frozen development decision, not a final-test result. The 2025–26
target was not read and cannot be used to revise these gates.

## Global explanation data

Step 3.10 refits explanation-only models on all 3,800 development examples. It
reports the naive outcome prior and explains Elo as a relative non-draw signal,
not a calibrated three-way model. Logistic explanations contain class-specific
coefficients on standardized, training-imputed predictors and an L2 magnitude.
CatBoost uses normalized target-free `PredictionValuesChange` structural
importance. Poisson reports its global log-rate terms and canonical-team UUID
attack and defence coefficients. Dixon–Coles reports rho and the exact four
adjusted low-score cells. These global summaries do not claim causality or
fixture-level attribution.

## Metrics and artifacts

The evaluator reports mean natural-log multiclass log loss, mean sum-of-three
classes Brier score and mean two-threshold normalized ranked probability score
using outcome order `home_win`, `draw`, `away_win`. Counts and all metric formulas
are versioned in the evaluation manifest.

Prediction JSON Lines do not contain observed outcomes or scores. The manifest
contains aggregate targets only in metric counts and pins the full training
manifest, input checksums, model contracts, partition definitions, fit
diagnostics, output checksum and deterministic ordering.

Run:

```powershell
plp-evaluate-models `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

Freeze the test identity and reproduce CatBoost tuning with:

```powershell
plp-tune-catboost `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

The second command writes the freeze manifest and selected development-fold
predictions only after re-running the raw-verifying training materializer. A
second unchanged invocation returns `already_current` with identical bytes.

Run Steps 3.6 through 3.8 with:

```powershell
plp-evaluate-advanced-models `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

This command re-runs raw-verifying training materialization and strictly loads
the CatBoost and freeze artifacts before producing the advanced development
dataset. It neither predicts nor scores 2025–26.

Apply Steps 3.9 and 3.10 with:

```powershell
plp-assess-models `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data
```

The command strictly loads every preceding artifact, revalidates the sealed
test identity and writes one deterministic assessment manifest. A repeated
unchanged invocation returns `already_current`.

The accepted CatBoost identity policy is packaged by Steps 4.1 and 4.2 without
changing these development results. Its versioned manifest embeds this
assessment and the untouched-test freeze and Step 4.3 may record only
development acceptance. See [Model Artifacts and Registry](model-artifacts.md).
