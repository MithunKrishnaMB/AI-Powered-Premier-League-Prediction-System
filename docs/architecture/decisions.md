# Architectural Decision Register

These decisions describe implemented behavior through the completed Milestone C.
A later decision may supersede an accepted decision only by recording the
replacement and its migration impact.

## ADR-001 — Backend-first typed Python package

**Status:** Accepted  
**Context:** The platform will contain ingestion, feature engineering, machine
learning, simulation, persistence, an API and eventually a frontend.  
**Decision:** Use an installable `src/`-layout package on 64-bit Python 3.14.7.
Use Pydantic models at external and domain boundaries, strict mypy, Ruff, pytest,
and branch coverage with a 90% minimum.  
**Consequences:** Packaging mistakes and invalid boundary data fail early. The
narrow Python support window improves consistency but may limit compatibility
with libraries that have not yet released Python 3.14 wheels.

## ADR-002 — Local quality gates; no CI/CD

**Status:** Accepted user constraint  
**Context:** The user does not want DevOps or YAML-based automation in the
project.  
**Decision:** Keep deterministic local quality commands but do not configure
GitHub Actions, CI/CD pipelines or deployment automation.  
**Consequences:** The code retains engineering checks without adding operational
complexity. Running the checks is a local milestone responsibility rather than
an automatically enforced remote gate.

## ADR-003 — Manifest-pinned immutable raw data

**Status:** Accepted  
**Context:** A source URL can return different bytes over time, which would make
model training irreproducible.  
**Decision:** Track source URL, allowed hosts, capture time, encoding, required
shape, byte count, row count and SHA-256 in a validated manifest. Store raw CSVs
outside Git, publish them without overwrite and reject checksum conflicts.  
**Consequences:** A training input is byte-identifiable and reproducible. Source
corrections require an explicit manifest review rather than a silent overwrite.

## ADR-004 — Separate source, canonical and quality boundaries

**Status:** Accepted  
**Context:** Provider column names and aliases should not leak into feature or
model code and valid individual rows can still form an invalid season.  
**Decision:** Keep three boundaries: typed Football-Data records, provider-neutral
domain records and cross-record competition validation. Resolve teams through
reviewed source aliases and stable UUIDs; do not use fuzzy matching.  
**Consequences:** Provider changes are isolated, domain code gets stable
identities and failures have clearer ownership. More models and validation code
are required than in a single permissive dataframe pipeline.

## ADR-005 — Deterministic canonical identity and materialization

**Status:** Accepted  
**Context:** Re-running ingestion must not create new fixture identities or
different bytes for equivalent data.  
**Decision:** Generate fixture UUIDv5 values from competition, season, home team,
and away team. Sort by kickoff and fixture ID, serialize JSON with stable key
ordering, hash the output and write a companion lineage manifest atomically.  
**Consequences:** Rebuilds are idempotent and auditable. The identity scheme is
appropriate for one ordered home/away pairing per league season; cup or replay
fixtures will require an additional identity component.

## ADR-006 — Preserve missing kickoff precision

**Status:** Accepted  
**Context:** Football-Data seasons 2015–16 through 2018–19 provide match dates but
not kickoff times. Inventing a precise time could cause false temporal ordering
and feature leakage.  
**Decision:** Store UTC timestamps, interpreting known times in
`Europe/London`. For date-only rows, use local noon solely as a deterministic
anchor and set `kickoff_precision=date_only`. Future feature state must be
calculated before and updated after the complete same-date batch.  
**Consequences:** Older history remains usable without pretending the source is
more precise than it is. Feature engineering must explicitly support batch
semantics.

## ADR-007 — Canonical JSON Lines before analytical storage

**Status:** Accepted for Milestone B  
**Context:** The first durable derived format should be inspectable, hashable,
and independent of a database or dataframe library.  
**Decision:** Materialize one deterministic JSON object per fixture plus a
per-season dataset manifest under ignored `data/interim/`.  
**Consequences:** Canonical records are easy to inspect and reproduce. JSON Lines
is not the most compact analytical format; a later feature milestone may add a
columnar processed format without replacing the canonical source of truth.

## ADR-008 — Versioned point-in-time feature-row boundary

**Status:** Accepted

**Context:** Model inputs must remain traceable to verified canonical data and
post-match targets or falsely precise historical kickoff ordering must not enter
pre-match predictors.

**Decision:** Represent each feature example with an immutable, provider-neutral
schema containing canonical fixture, season and team identities; UTC kickoff
and feature-cutoff boundaries; a separately versioned predictor collection; an
optional nested training label; and checksum-pinned canonical, historical and
raw-source lineage. Derive a deterministic UUIDv5 row ID from the semantic row
and input lineage. For date-only fixtures, require the cutoff to precede the fixture's
`Europe/London` calendar date; chronological processing updates state only after
the complete same-date batch. Predictor representability does not grant
eligibility and retained bookmaker columns remain unapproved.

**Consequences:** Predictors and targets cannot be conflated accidentally by the
wire structure, equivalent inputs have stable identities and every row can be
traced to a manifest-verified source artifact. Feature definitions and material
calculations remain separate versioned responsibilities.

## ADR-009 — Pre-batch within-season rolling state

**Status:** Accepted; cross-season portion superseded by ADR-012 for predictor
schema version 2

**Context:** Historical sources may omit kickoff times, optional statistics may
be missing and early-season teams do not have comparable Premier League history
in the current season.

**Decision:** Reset version 1 feature state at each season boundary and use a
five-match form window alongside season-to-date aggregates. Snapshot all team
state before each chronological batch and commit fixture observations only after
every row in that batch has been created. If any fixture on a Premier League
calendar date in `Europe/London` is date-only, batch the whole local date. Retain
missing optional statistics as null averages with explicit observation counts.
Derive promoted status only from the
reviewed season registry, rest and congestion from prior fixture dates and
season progress from prior processed fixtures and known membership size.

**Consequences:** Current results cannot affect current predictors, unknown
within-day ordering cannot leak and missing statistics are distinguishable
from observed zeros. Version 1 deliberately has no cross-season carryover;
ADR-012 introduces reviewed, explicitly separate carryover in predictor schema
version 2 without changing factual within-season observation counts.

## ADR-010 — Deterministic processed feature artifacts

**Status:** Accepted

**Context:** In-memory feature rows are insufficient for reproducible training;
the persisted bytes must remain tied to the exact verified raw and canonical
inputs, feature schema and temporal semantics.

**Decision:** Materialize one compact, key-sorted JSON object per feature row
under ignored `data/processed/`, ordered by cutoff, kickoff and deterministic
row UUID. Publish an adjacent deterministic manifest containing output checksum
and count, all feature-related schema versions, the complete ordered predictor
schema and checksum, processing parameters, recursive historical-context
checksum, canonical fixture checksum and registry versions and raw source
checksum and capture identity. Invoke the existing checksum-verifying canonical
materializer for every required predecessor before building a target season,
validate canonical bytes against their manifests and publish files through
atomic replacement.

**Consequences:** Training inputs are byte-identifiable, stale generated outputs
are replaced without partial files and unchanged builds return
`already_current`. The JSON Lines representation is intentionally inspectable;
a later columnar representation must retain the same lineage and deterministic
semantics rather than silently replacing them.

## ADR-011 — Reproducible model-ready training dataset

**Status:** Accepted

**Context:** Reproducible feature files still need a single validated,
model-ready boundary. Combining seasons without pinning each input manifest or
without keeping post-match outcomes separate would allow provenance drift or
target leakage before model development begins.

**Decision:** Project every labeled feature row into immutable `TrainingExample`
schema version 1, retaining its point-in-time predictors and placing the result
and score only in a separate required `target`. Combine all manifest-listed
seasons in deterministic kickoff/UUID order. Bind each example to its source
feature row and season-specific feature dataset. Publish JSON Lines with a
versioned manifest that pins the training checksum, predictor and target
schemas, tracked input-file checksums and every feature, canonical and raw
source checksum plus each historical-context checksum. Re-run the raw-verifying
canonical and feature materializers before every combined build. Do not select a
temporal split or fit a model in this step.

**Consequences:** The first model-ready corpus is byte-reproducible and rejects
unknown or cross-season lineage, modified source artifacts, incomplete targets,
and predictor drift. Later model milestones must choose chronological training
and evaluation windows explicitly rather than treating this combined historical
corpus as a randomly splittable dataset.

## ADR-012 — Explicit season-opening priors

**Status:** Accepted

**Context:** Pure within-season aggregates are empty at kickoff of a season and
unstable during its first matches. Silently pooling future matches, unverified
lower-division data or pseudo-observations into factual counts would create
leakage or misleading denominators.

**Decision:** Predictor schema version 2 adds a separate opening-prior contract.
A continuing club uses its own immediately preceding Premier League result and
goal aggregates. A promoted club uses that preceding league's aggregate because
Championship results are not present in the verified dataset. Every club in the
first tracked season uses a fixed neutral prior: equal win/draw/loss rates, 4/3
points per match and 1.5 goals for and against. Blend the prior with observed
current-season results using a fixed five-match pseudo-weight, while leaving all
factual match and statistic counts unchanged. Expose the prior source through
mutually exclusive predictor flags and record every constant and source policy
in the feature manifest.

**Consequences:** Opening fixtures have finite, explicit form estimates without
using future information or pretending that pseudo-matches occurred. Promoted
clubs receive a deliberately coarse league fallback; introducing verified
Championship history would require a new prior schema and provenance chain.

## ADR-013 — Batch-safe cross-season Elo

**Status:** Accepted

**Context:** Elo supplies a compact strength estimate, but it can leak when one
fixture on an uncertain date updates a rating used by another fixture in the
same batch. Offseason and promoted-team initialization must also be explicit.

**Decision:** Elo schema version 1 starts at 1500, adds 65 rating points for home
advantage, uses K-factor 20 and a 400-point logistic scale and retains 75% of a
continuing club's deviation from 1500 between seasons. Promoted clubs and every
club in the first tracked season initialize at 1500. Calculate all expected
scores and result deltas from one pre-batch rating snapshot, then apply the
accumulated zero-sum deltas after the batch. Persist ratings and expected scores
only as pre-match predictors. Bind cross-season state to a recursive checksum of
all preceding verified canonical and raw inputs plus the parameter policy.

**Consequences:** Exact and date-only fixtures share the same leakage boundary,
reruns produce identical rating histories and changed predecessor data changes
downstream row identities. Elo expected score remains a benchmark signal rather
than a calibrated three-outcome probability model.

## ADR-014 — Fixed chronological probabilistic development evaluation

**Status:** Accepted

**Context:** Model comparison needs deterministic three-way probabilities and
metrics without exposing evaluation targets during prediction or consuming the
most recent season before the formal test-freeze step.

**Decision:** Use 2015–16 through 2022–23 as the fixed holdout reference window
and 2023–24 through 2024–25 as its evaluation window. Also evaluate five
expanding folds: train through each preceding season and validate one complete
season from 2020–21 through 2024–25. Keep 2025–26 outside every development fit
and metric. Fit the naive outcome frequency and all preprocessing only on each
reference window. Predictions remain target-free and evaluation joins targets
only by immutable training-example ID after prediction. Score mean natural-log
multiclass log loss, mean three-class Brier score and normalized ranked
probability score. Re-run the existing raw-verifying training materializer before
evaluation and publish deterministic JSON Lines plus a checksum-pinned manifest.

**Consequences:** No random split or incomplete simultaneous batch can enter
development evaluation and the most recent season remains available for Step
3.4. Holdout and fold estimates are transparent but are development results,
not final test performance.

## ADR-015 — Deterministic benchmark bridge and multinomial logistic baseline

**Status:** Accepted

**Context:** Elo expected score is binary-like expected match score, not a
calibrated home/draw/away distribution, while the first fitted classifier must
handle nullable, differently scaled predictors without leaking evaluation
statistics.

**Decision:** The naive benchmark emits the reference-window three-way outcome
frequency. The Elo benchmark fixes draw mass to the same reference draw
frequency and allocates the remaining mass according to the two complementary
pre-match Elo expected scores. It does not tune or calibrate that mapping. The
logistic baseline uses every ordered predictor from `epl-pre-match` version 2,
maps booleans to zero/one, mean-imputes nulls and standardizes columns using only
the current training window, then fits a three-class L2-regularized softmax model
with a fixed full-batch Adam contract in NumPy float64. No random initialization,
feature selection, hyperparameter tuning or model serialization occurs.

**Consequences:** All methods preserve draws and can be compared with proper
probabilistic scores. Preprocessing is fold-local and deterministic. The
logistic result is an evaluated development baseline, not a tuned, calibrated or
registered production model.

## ADR-016 — Target-free untouched-test freeze

**Status:** Accepted

**Context:** Excluding 2025–26 from earlier development evaluation protects it
in practice, but a durable test boundary also needs an explicit identity,
policy and lineage contract. Persisting its outcomes, scores or aggregate label
statistics in that contract would unnecessarily expose the test target.

**Decision:** Designate the complete 380-fixture 2025–26 season as
`untouched-test-2025-2026-v1`. Build its freeze only after the existing
raw-verifying training materializer succeeds. Hash a deterministic sequence of
training-example, feature-row, fixture, season, cutoff, kickoff,
source-feature-dataset and predictor-payload identities; never read or serialize
the target. Pin the source training dataset and manifest checksums. State that
target access is prohibited until an explicit one-time final-test evaluation
and that the season is excluded from development training, tuning, selection,
calibration and acceptance. Publish a canonical, atomically replaced JSON
manifest whose unchanged rerun is byte-identical.

**Consequences:** Test membership and predictor provenance can be audited now
without seeing the answers. A target change cannot change the freeze, while a
changed predictor, cutoff, identity or upstream training artifact does. Step
3.4 does not consume the test or produce a final performance claim.

## ADR-017 — Deterministic development-only CatBoost tuning

**Status:** Accepted

**Context:** A nonlinear tabular benchmark is useful only if its search space,
temporal evaluation and runtime behavior are fixed before the untouched test is
opened. Broad or stochastic search would weaken reproducibility and invite
development overfitting.

**Decision:** Pin CatBoost 1.2.10 and evaluate exactly three reviewed candidates:
200 depth-4 trees at learning rate 0.03 and L2 3; 300 depth-5 trees at learning
rate 0.03 and L2 5; and 200 depth-6 trees at learning rate 0.05 and L2 10. Use
all 175 approved predictors and CatBoost's native missing-value handling. Every
fit is CPU-only and single-threaded with seed 20260912, no bootstrap, zero
random strength, symmetric trees, `Min` NaN handling and no file writes. Score
each candidate on the existing five expanding folds through 2024–25. Select by
minimum aggregate natural-log loss, then Brier score, normalized ranked
probability score and candidate ID. Persist only the selected candidate's 1,900
target-free fold predictions and a typed report for every candidate; fit the
winner once on all 3,800 development rows in memory. Do not serialize a model or
read, predict or score 2025–26.

**Consequences:** Candidate comparison is chronological, bounded and
reproducible and CatBoost preserves the three explicit Premier League outcome
probabilities. The selected development configuration is evidence for later
calibration work, not a registered production model or final-test result.

## ADR-018 — Expanding prior-out-of-fold calibration

**Status:** Accepted

**Context:** Fitting and assessing a calibrator on the same predictions gives an
optimistic result, while using 2025–26 would violate the untouched-test policy.
The selected CatBoost artifact already supplies one out-of-fold prediction for
each development fixture from 2020–21 onward.

**Decision:** Assess a single bounded temperature-scaling candidate against an
identity policy. Use 2020–21 only as the first calibration-history season. For
each season from 2021–22 through 2024–25, fit temperature on every preceding
CatBoost out-of-fold season and apply it to the next complete season. Minimize
natural-log loss with a deterministic 96-iteration golden-section search over
temperatures from 0.25 through 4.0. Select by aggregate log loss, then Brier
score and normalized ranked probability score on the paired 1,520 predictions.
Fit a final diagnostic temperature on all 1,900 development out-of-fold rows,
but do not serialize it or apply it to the untouched test.

**Consequences:** Calibration assessment never uses a prediction's own target
or crosses a whole-season boundary. Temperature scaling was worse on the paired
development population, so the adopted calibration strategy is identity. The
temperature-transformed development rows remain an auditable rejected-candidate
artifact, not a production calibration claim.

## ADR-019 — Independent-Poisson and Dixon–Coles score baselines

**Status:** Accepted

**Context:** Three-way classifiers do not produce scoreline distributions.
Score baselines must handle promoted clubs, preserve deterministic fitting and
remain comparable inside the established chronological development folds.

**Decision:** Fit an independent-Poisson model with one global intercept, home
advantage and canonical-team attack and defence coefficients. Use only scores
from the current reference seasons; an unseen canonical team receives neutral
zero attack and defence coefficients. Apply L2 strength 0.01 and fixed
2,000-iteration full-batch Adam with learning rate 0.03, beta values 0.9 and
0.999 and epsilon `1e-8`. Bound expected goals to 0.05 through 6.0 and construct
a normalized 0–40 by 0–40 score grid before projecting it to three outcomes.

Fit Dixon–Coles rho separately on the same reference rows by deterministic
scalar likelihood search over `[-0.15, 0.025]`. Adjust only 0–0, 0–1, 1–0 and
1–1, then renormalize. Do not add time decay or jointly refit the Poisson
coefficients in this baseline. Evaluate both models on all five expanding folds
and fit final diagnostics on all 3,800 development fixtures. Persist target-free
three-way projections and contracts, not score grids or model weights.

**Consequences:** The platform now has reproducible score-generating baselines
without odds, fuzzy identities, within-season random splits or test access.
The fitted development rho is negative, but the adjusted model did not improve
the base Poisson log loss. Model acceptance remains a separate Step 3.9 policy
decision fixed before final-test access.
