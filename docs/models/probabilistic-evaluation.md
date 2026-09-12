# Probabilistic Development Evaluation

## Scope

Steps 3.1 through 3.5 implement deterministic naive and Elo benchmarks, an
L2-regularized multinomial logistic baseline, expanding-season walk-forward
validation, a formal untouched-test freeze and bounded CatBoost tuning. They do
not implement calibration, a final untouched-test evaluation, score models, a
model registry or serving.

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
