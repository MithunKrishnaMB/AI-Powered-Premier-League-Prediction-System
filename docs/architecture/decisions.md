# Architectural Decision Register

These decisions describe implemented behavior through Milestone F.
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

## ADR-020 — Frozen development acceptance and global explanations

**Status:** Accepted

**Context:** Development comparison needs a pre-test pass/fail policy and a
single champion without rewarding incomplete populations. Explanation outputs
must respect each model's structure and must not be mistaken for calibrated Elo
probabilities, fixture-level causality or registered model artifacts.

**Decision:** Compare every candidate against naive on the same five complete
expanding folds and 1,900 rows. Require exact population coverage, at least 2%
aggregate log-loss improvement, no aggregate Brier or RPS regression and at
least three fold-level log-loss wins. Select among accepted methods by minimum
log loss, then Brier, RPS and method ID. Use the selected identity calibration
policy for CatBoost; exclude the four-fold temperature diagnostic as a separate
candidate. All five methods pass and CatBoost is champion.

Refit explanation-only models on all 3,800 development rows. Persist naive
frequencies, the Elo bridge contract, standardized multinomial coefficients,
normalized CatBoost `PredictionValuesChange`, canonical-UUID Poisson attack and
defence log-rate terms and Dixon–Coles rho and adjustment scope. Reverify raw
lineage and all evaluation checksums first. Persist one canonical assessment
manifest, not model weights, registry state or test output.

**Consequences:** Acceptance is reproducible, population-matched and fixed
before final-test access. Explanations are auditable global summaries appropriate
to each model family. The 2025–26 target remains sealed; final-test evaluation,
serialization, promotion, simulation and deployment remain out of scope.
Milestone D is closed out with CatBoost plus identity calibration as the
development policy. Step 4.1 is next and may define artifact layout and schema
only; serialization begins in Step 4.2 and registry-state behavior in Step 4.3.
The completed implementation is recorded in local commit `3ac10a2`.

## ADR-021 — Content-addressed model artifact contract

**Status:** Accepted

**Context:** The selected development model needs stable semantic and physical
identity before model bytes or mutable registry state can be introduced. A
manifest that omits preprocessing, runtime or upstream acceptance lineage could
load successfully while changing prediction semantics.

**Decision:** Use layout
`artifacts/models/v1/<model-id>/<artifact-id>/` with one canonical manifest and
exactly two ordered required components: a stateless numeric preprocessor and a
CatBoost classifier. Derive distinct UUIDv5 model, component, artifact and
manifest identities from compact canonical identity payloads. Pin exact Python,
CatBoost, NumPy, Pydantic, tzdata, predictor-schema and three-outcome contracts.
Embed the training, assessment and untouched-test-freeze manifests and
cross-check all evaluation and prediction checksums. Represent identity
calibration and the absence of a selected score model explicitly. Reject
unknown fields, versions, paths, components and compatibility drift.

**Consequences:** The selected CatBoost depth-6 identity policy is portable and
auditable without conflating its semantic model identity, physical bytes or
future registry state. The artifact produces three-way probabilities only and
cannot be treated as a scoreline model.

## ADR-022 — Canonical CatBoost JSON serialization and reload

**Status:** Accepted

**Context:** Equivalent CatBoost fits produce different default binary and JSON
bytes because exports contain a random GUID and wall-clock finish time. Raw
export checksums therefore cannot satisfy deterministic artifact requirements.

**Decision:** Fit the selected model only on the 3,800 development examples
after the existing raw-verifying assessment and training workflows succeed.
Export CatBoost's supported JSON format, replace only its non-predictive model
GUID and finish time with the stable model ID and fixed epoch, then apply the
platform's canonical JSON encoding. Serialize the stateless preprocessor
contract separately. Atomically publish components before the manifest, verify
size and SHA-256, reload CatBoost, require 200 trees, 175 features and class
order 0, 1, 2 and compare all development predictions within four float64
machine epsilons. Never read or predict the untouched test season.

**Consequences:** Repeated builds have stable bytes and checksums while retaining
CatBoost's supported loader and numerical behavior. The maximum permitted
round-trip tolerance is explicit and much smaller than the persisted
probability precision.

## ADR-023 — Append-only development registry with sealed activation

**Status:** Accepted

**Context:** Registry state must not mutate the immutable artifact or imply that
development acceptance is production approval. The final-test target is still
sealed and there is no typed final-test evidence contract.

**Decision:** Store an immutable registry entry and deterministically named,
checksum-linked events below `artifacts/registry/v1/entries/<entry-id>/`.
Registration fully verifies the artifact and creates `candidate`.
`development_accepted` requires the embedded frozen assessment and selected
policy. Candidate and development-accepted entries may transition to terminal
`rejected` with a reason. Reserve `active` and `retired`, but fail every active
promotion with `final_test_evidence_required` until a later explicit step adds
and verifies typed one-time final-test evidence. Do not keep a mutable active
pointer in Step 4.3.

**Consequences:** Registry history is deterministic and tamper-evident, no
development-only result can silently become active and future activation must
extend the schema rather than bypass the untouched-test boundary.

## ADR-024 — Explicit scoreline-distribution simulation boundary

**Status:** Accepted

**Context:** The selected CatBoost classifier emits only home-win, draw and
away-win probabilities. A season simulator needs scores for goal difference,
goals scored and head-to-head away-goal ranking, but three-way probabilities do
not identify a unique or validated score distribution.

**Decision:** Require every remaining `SimulationFixture` to carry a strict,
content-identified `FixtureScorelineDistribution`. Bind it to canonical fixture
and team UUIDs, ordered positive probabilities summing to one and scores from 0
through 40. Do not provide any classifier-to-scoreline conversion. Preserve the
existing UTC and date-only simultaneous-batch chronology in canonical season
inputs.

**Consequences:** Table mechanics can be built and tested without pretending
that the registered artifact has an unsupported scoreline capability. A later
integration step must explicitly choose and provenance the distribution source.

## ADR-025 — Stateless SHA-256 scoreline draws

**Status:** Accepted

**Context:** A mutable pseudorandom generator makes sampled results depend on
fixture iteration order and complicates later vectorization and exact
reproduction.

**Decision:** Derive each unit-interval draw from SHA-256 over schema version,
unsigned 64-bit seed, non-negative simulation index and canonical fixture UUID.
Use the first big-endian 64 bits divided by `2^64`, then apply inverse-CDF
selection in canonical score order. Bind sampled-result UUIDv5 identity to the
distribution, seed, index and selected score.

**Consequences:** Reordering or parallelizing fixtures cannot change a given
fixture's draw. The algorithm is portable, explicit and independent of NumPy's
mutable RNG state.

## ADR-026 — Fixture-ledger table state and official ranking

**Status:** Accepted

**Context:** Simulation tables must reconcile exactly with sampled results and
must not use a convenient but unofficial alphabetical or identifier tiebreak.

**Decision:** Rebuild immutable rows from a unique, canonically ordered fixture
ledger. Award three points for a win and one for a draw. Rank final rows by
points, goal difference, goals scored, head-to-head points and head-to-head away
goals. If tied clubs remain equal, raise `UnresolvedTableTieError` because the
official rule calls for a separately prescribed neutral-venue playoff when a
material placing must be determined.

**Consequences:** Every row is auditable back to results and every reported
position follows official statistical criteria. ADR-027 defines how multi-run
aggregation represents the exceptional playoff boundary without silently
inventing a sporting result.

## ADR-027 — Fixed vectorized simulation batch and fractional playoff mass

**Status:** Accepted

**Context:** Ten thousand simulations must remain reproducible without building
10,000 mutable object graphs. An unresolved official playoff also cannot be
silently replaced by an identifier sort or an unsupported match model.

**Decision:** Fix simulation algorithm version 1 at exactly 10,000 runs. Sample
each explicit fixture distribution across the run axis, accumulate table values
in NumPy and store read-only score and table matrices plus a float64 position-
mass tensor. Rank by the official statistical criteria. If a remaining tie
occupies multiple positions, distribute each tied team's mass equally across
those positions while the single-table API continues to reject a request for a
unique order. Bind the run UUID to complete canonical input, seed, algorithm
version and run count.

**Consequences:** Every team and position retains unit probability without
claiming a fictional playoff winner. Repeated inputs yield identical run
identity and matrix values and later parallel execution cannot change fixture
draws.

## ADR-028 — Complete position and threshold aggregation

**Status:** Accepted

**Context:** Consumers need probabilities rather than individual simulated
tables and partial position outputs can hide lost or duplicated probability
mass.

**Decision:** Aggregate float64 position mass into a complete 20-position vector
per team. Derive expected points, goals for, goals against and goal difference,
plus champion, top-four, top-six and relegation probabilities. Require each team
and position to sum to one and the four league thresholds to total one, four,
six and three. Derive a content-bound UUIDv5 summary identity.

**Consequences:** Aggregates are self-checking, deterministic and explicit about
all finishing positions. No database schema, API representation or production
score-distribution provider is implied.

## ADR-029 — Persistence begins with a schema-only boundary

**Status:** Accepted

**Context:** Milestone E closes with deterministic artifact, registry and
simulation contracts, while Milestone F introduces PostgreSQL persistence. A
database design that collapses immutable provenance, treats development
acceptance as activation or assumes that classifier probabilities are scoreline
distributions would invalidate completed guarantees before any migration exists.

**Decision:** Begin Milestone F with Step 5.1 as an entity-relationship design
step against the data and artifacts already produced. Model canonical fixtures,
feature and training lineage, evaluations, artifact components and manifests,
append-only registry events, explicit simulation inputs and aggregate summaries
without configuring a database, initializing Alembic or creating migrations.
Preserve content identities, canonical checksums, three-way outcome order,
predictor/target separation and the sealed 2025–26 final-test boundary. Keep a
development-accepted registry entry distinct from an active model and keep
scoreline distributions independent of the CatBoost classifier.

**Consequences:** Step 5.1 can settle entities, keys, relationships, constraints
and ownership before operational database choices are introduced. Connections
remain Step 5.2, Alembic remains Step 5.3 and migrations remain Steps 5.4–5.7;
no persistence implementation may bypass raw-source or evaluation lineage.

## ADR-030 — Lossless PostgreSQL projection of immutable artifacts

**Status:** Accepted

**Context:** The implemented pipeline uses stable UUIDv5 and content-derived
identities, exact canonical JSON or JSON Lines bytes, checksum-pinned manifests,
strictly ordered predictors and simulation inputs and an append-only registry.
Normalizing only selected values into mutable relational rows or storing JSON as
`jsonb` alone would lose byte identity, ordering or historical context. Generated
database identities would also break references already embedded in artifacts.

**Decision:** Use existing UUIDs, textual dataset IDs and SHA-256 values as
primary keys. Tables without a domain identity use owner-plus-ordinal composite
keys; PostgreSQL must not generate replacement identities. Store every source,
dataset, manifest, model component and registry event as an independently owned
entity linked to its exact immutable `bytea` content and server-verified SHA-256.
Use explicit ordinals for every canonical order and typed normalized projections
for querying, while keeping original bytes authoritative.

Separate stable fixtures from immutable fixture revisions so a postponed match
can retain identity without overwriting history. Keep predictor values and
training targets in separate relations and keep classifier, preprocessing,
calibration, score-model, physical-component and registry metadata distinct.
Registry state is derived from checksum-linked events; schema version 1 rejects
activation because typed final-test evidence does not exist.

Represent scoreline distributions independently of three-way predictions and
attach separate immutable producer provenance without changing their content
identity. Persist simulation inputs in declared order, require algorithm version
1 and exactly 10,000 runs and preserve `int64`, `int16` and `float64` result
component contracts. Preserve date-only whole-date simultaneous batches.

Use immediate constraints for local validity and deferred constraint triggers
for cross-row ordering, membership, probability mass, checksum-chain and
aggregate invariants. All historical and derived entities are immutable and use
restrictive foreign-key deletion; archive, rejection, retirement and
supersession do not delete provenance.

**Consequences:** PostgreSQL can support relational queries without replacing
the files' deterministic identity or provenance semantics. Exact import and
repository behavior remain later steps, as do connections, Alembic and
migrations. The design requires explicit database digest, immutability and
deferred-validation support in those migrations, but it does not configure or
connect to PostgreSQL in Step 5.1.

## ADR-031 — Isolated unprivileged PostgreSQL connection targets

**Status:** Accepted

**Context:** Development and integration tests need local PostgreSQL access,
but sharing one database or connecting the application as the cluster
administrator could let a test destroy development state or give application
code unnecessary authority. URLs contain credentials and must not enter Git,
logs, command output or Alembic configuration.

**Decision:** Use SQLAlchemy 2.0 with the psycopg 3 driver on Python 3.14.7.
Connect to separate `pl_platform_dev` and `pl_platform_test` databases through
the dedicated `pl_app` login. The role owns those databases but is explicitly
not a superuser and cannot create databases, roles or replication slots. Keep
both URLs as `SecretStr` values in the ignored local `.env`, expose only
password placeholders in `.env.example` and redact URL/DSN logging keys.

Require the `postgresql+psycopg` scheme and explicit host, port, role, password
and database. Reject URLs that resolve to the same host, port and database even
when credentials or host casing differ. A read-only connection check must
validate the reported database and role against the URL, PostgreSQL 16 or
newer, UTC and the restricted role flags, including row-security bypass.
Engine creation must remain lazy, bounded and health checked.

**Consequences:** Development and test state are isolated while schema
migrations remain possible through database ownership. Cluster-level setup
still requires the existing administrator once. Production credentials and
topology remain undefined and no database table or artifact persistence is
introduced by this decision.

## ADR-032 — Secret-free Alembic initialization before schema revisions

**Status:** Accepted

**Context:** Alembic must be initialized in Step 5.3, while the first identity,
season and fixture migration belongs to Step 5.4. Embedding a URL in
`alembic.ini` would duplicate secret handling and make accidental target
selection easier.

**Decision:** Keep `alembic.ini` URL-free and resolve the connection from typed
`PLP_*` settings inside `migrations/env.py`. Select only development or test
from `PLP_ENVIRONMENT` and reject production. Use a `NullPool` online, force
UTC, enable type and server-default comparison, include PostgreSQL schemas and
run each future revision transactionally. Support an externally supplied
connection for later integration tests. Initialize the version directory and
typed revision template without creating a revision, metadata model or database
object.

**Consequences:** `alembic heads` and `alembic history` are empty after Step
5.3 by design. Step 5.4 can add the first reviewed revision against the
finalized ER model without changing credential policy. Autogeneration cannot
silently invent a schema before explicit metadata is introduced.

## ADR-033 — Linear, fail-closed PostgreSQL schema revisions

**Status:** Accepted

**Context:** The Step 5.1 ER design spans immutable byte lineage, stable
identity, point-in-time features, training/evaluation evidence, model artifacts,
append-only registry history and simulation contracts. Referential dependencies
cross roadmap steps, while downgrade behavior must remain deterministic and no
revision may import artifacts or expose the sealed final-test targets.

**Decision:** Implement Steps 5.4 through 5.7 as four explicit, linear,
transactional Alembic revisions. Use PostgreSQL domains, named checks,
content/UUIDv5 identity checks, restrictive foreign keys, deferred constraint
triggers and immutable update/delete guards. Add later cross-schema foreign
keys only after their parent relations exist and remove those links first on
downgrade. Preserve exact bytes in `lineage.stored_object`; normalized tables
remain query projections rather than replacements for canonical artifacts.

Keep the 2025–26 freeze membership target-free, reject registry activation in
schema version 1 and require scoreline-capable provenance for model-produced
simulation distributions. The current CatBoost artifact explicitly lacks that
capability. Require exactly 10,000 simulations, unsigned 64-bit seeds, exact
NumPy dtype/shape roles, whole-date batches for date-only fixtures and complete
20-by-20 position probability mass. The provider cache is only a schema shape;
no provider is configured. Revisions create structures only and do not import,
persist or evaluate repository artifacts.

**Consequences:** A fresh database can upgrade to one head and downgrade to an
empty application schema without losing migration history correctness. Invalid
identity, provenance, chronology, runtime, registry or probability state fails
at the database boundary. Steps 5.8 and 5.9 build and verify the repository
boundary on this unchanged four-revision head.

## ADR-034 — Raw-gated immutable aggregate repositories

**Status:** Accepted

**Context:** The schema can reject invalid rows, but persistence must also retain
the exact produced bytes, existing content identities and artifact boundaries.
An upsert that silently replaces history, reconstructs JSON from relational
values or begins writing before source verification would weaken the completed
lineage guarantees.

**Decision:** Accept only frozen `AggregateWritePlan` values containing exact
`StoredObject` bytes and allowlisted `ImmutableRow` projections. Keep the
aggregate kinds for identity/reference data, raw captures, canonical fixtures,
features/Elo, training, evaluation, model artifacts, registry, provider cache,
scoreline distributions, simulation inputs, runs and summaries distinct. Use
only caller-supplied UUID, textual and SHA-256 identities and require rows in
foreign-key dependency order.

Before opening a database transaction, verify every file in the reviewed raw
manifest and compare any aggregate raw-artifact or historical-manifest lineage
with that evidence. Within one serializable transaction, insert exact bytes
first, insert normalized projections second, force every deferred constraint to
run and reload-compare every supplied field and byte before commit. Conflict
handling is retry-only: `ON CONFLICT DO NOTHING` is followed by exact comparison
and never hides different existing content. Map database failures to stable,
non-secret categories.

**Consequences:** Retrying an identical aggregate is idempotent while a reused
identity with different content fails closed. The repository cannot bypass raw
manifest verification, change immutable history, access the sealed target,
activate a development-accepted model or infer scorelines from three-way
classifier probabilities. Production corpus import remains a separate,
explicitly authorized operation.

## ADR-035 — Transaction and PostgreSQL constraint verification

**Status:** Accepted

**Context:** Unit validation alone cannot prove transaction rollback, deferred
constraint execution, immutable database guards or retry behavior against the
real PostgreSQL schema.

**Decision:** Run Step 5.9 integration tests only against the isolated
`pl_platform_test` database at exact Alembic head `f0004_step_5_7`. Exercise
successful atomic persistence, byte-for-byte idempotent retry, conflicting
existing content, rollback after a later row constraint fails, direct checksum
rejection, immutable update rejection and a raw-verification failure that opens
no write transaction. Retain the existing empty-to-head, head-to-base and
schema-introspection tests.

**Consequences:** The executable test boundary verifies both application and
database enforcement without importing the production artifact corpus or
modifying development data. The 2025–26 target stays sealed, the registry has no
active model and current-provider, API, deployment, frontend and CI/CD work
remain outside Milestone F. The final Python 3.14.7 suite contains 389 passing
tests with 90.53% branch coverage; both isolated databases finish at migration
head with zero application rows. Commit `22e595a` records this boundary.

## ADR-036 — Provider-neutral current-season capability boundary

**Status:** Accepted

**Context:** Milestone G needs current-season teams, fixtures, state changes,
official results and standings without selecting a provider before its
capabilities and semantics are understood. Provider IDs, timestamps and status
codes cannot be allowed to leak into canonical identity or predictors. Exact
responses also need a future cache projection without authorizing network or
database behavior in Step 6.1.

**Decision:** Define five provider-neutral capabilities: current-season teams,
current-season fixtures, fixture status, completed results and standings.
Separate provider availability (`supported`, `unsupported` and
`temporarily_unavailable`) from the platform's required/optional classification;
standings are optional and the other four operations are required.

Use distinct source-scoped types for provider competition, season, team and
fixture identifiers. Pair provider scope with an explicit canonical competition
and season, but never treat an external ID as a canonical UUID. Require reviewed
exact team aliases or external-ID mappings, reject unknown identities and
prohibit fuzzy matching.

Preserve provider kickoff source timezone, local date, UTC instant and exact or
date-only precision. Local noon is only the date-only anchor and a date
containing a date-only fixture remains one simultaneous batch. Make
`retrieved_at` the conservative knowledge boundary; provider timestamps cannot
backdate feature availability.

Represent scheduled, in-progress, postponed, cancelled, abandoned and finished
states explicitly. Only finished records with a consistent official full-time
score are completed. Status observations are score-free and abandoned or
cancelled records cannot become results. Add `abandoned` to the in-memory
canonical status contract without changing the existing migration in Step 6.1.

Use strict immutable request, response, pagination, quota, compatibility,
provenance and sanitized-error contracts. Hash canonical credential-free
request identity bytes and exact provider response bytes separately. Map the
five operations onto the existing cache values (`metadata`, `fixtures`,
`results`, `standings`) while retaining the exact operation and compatibility
inside request identity. Do not persist a response; cache expiry remains Step
6.4.

Keep the existing 175-name predictor schema unchanged. Provider identities and
status are control data, completed scores can update only later rolling state,
standings require a separately reviewed feature change and unmodeled fields and
betting odds are retained-only and predictor-prohibited.

**Consequences:** Provider selection can be reviewed later against an explicit
capability manifest and adapters have typed fail-closed inputs. Equivalent
requests and exact responses are content-identifiable and can fit the existing
cache schema without losing bytes or compatibility. Step 6.1 adds no provider
implementation, authentication, network call, retry, cache write,
synchronization, production import, test evaluation, active promotion, API,
deployment, frontend or CI/CD configuration. Step 6.2 is limited to explicit
fixture/team transformation and must preserve these boundaries.

## ADR-037 — Current transformation, safe transport and immutable cache

**Status:** Accepted

**Context:** The provider-neutral contracts need executable transformation and
transport behavior before fixture synchronization. External identities must not
alter canonical UUID rules, secrets must not enter request identity or logs,
and cache freshness must not weaken exact-byte provenance or immutable
repository behavior.

**Decision:** Resolve current teams only through reviewed exact external IDs or
aliases, reject conflicts and unknown identities, verify canonical season
membership and derive current fixture UUIDs with the same competition/season/
home/away UUIDv5 function used by historical ingestion. Retain the full capture
and provider-local kickoff semantics. Reject finished observations until the
separate completed-result reconciliation step and group any date containing a
date-only fixture as one simultaneous batch.

Provide a vendor-neutral HTTPS executor with exact host allowlisting,
credential-free URLs and request identities, `SecretStr` header authentication,
disabled redirects, bounded bodies/timeouts, a process-local conservative quota
ledger and at most five deterministic retry attempts. Log typed identifiers and
decisions only—never URLs, headers, bodies, credentials or raw exception text.

Project successful captures into the existing provider-cache schema without a
new migration. Persist canonical request identity bytes and exact response bytes
as separate checksum-keyed objects, then link retrieval, expiry and HTTP
metadata through one immutable cache row using the established raw-manifest-
gated serializable repository. A cache read returns only the latest exact
request match that is fresh at the explicit lookup instant and revalidates
operation, source, checksums, key, media metadata and compatibility.

**Consequences:** Steps 6.2 through 6.4 remain provider-neutral and do not
synchronize football tables, parse a vendor payload or select credentials.
Retries are bounded and permanent errors fail immediately. Exact responses can
be replayed and reparsed under pinned compatibility without losing their bytes.
Step 6.5 can consume deterministic transformed fixtures and cached provenance,
but must first add persistence support for `abandoned`. Predictor/target,
sealed-test, model-promotion and simulation boundaries remain unchanged.

## ADR-038 — Separate current facts, observations and reconciled snapshots

**Status:** Accepted

**Context:** Historical fixture revisions are immutable canonical-dataset
members, while current providers can revise kickoff and state and repeat the
same fact in many responses. Completed scores must become a single official
ledger without losing repeated provenance. Provider tables can disagree with
or lead locally available result evidence, so standings cannot silently become
derived truth or predictor input.

**Decision:** Share only stable `football.fixture` UUIDs with historical data.
Persist current fixture facts as content-derived immutable revisions and record
each exact provider response separately as an observation referencing the
existing cache. Keep provider fixture IDs in a dedicated exact mapping. Persist
batches with all contributing cache keys and UUID-ordered members, enforcing
whole-provider-local-date membership whenever any fixture is date-only.

Persist one immutable, score/outcome-consistent completed result per canonical
fixture, plus repeatable cache-provenanced observations. Require a prior valid
fixture observation and fail on provider-reference conflict, terminal cancelled
or abandoned state, completion before kickoff or a conflicting official score.

Persist standings only as complete 20-team snapshots with separate provider
team references. Reconcile every row first in the typed application boundary
and again in a deferred database trigger against official results known by the
snapshot retrieval instant. Keep standings outside the approved predictor
schema. Add `abandoned` to the historical score-free fixture status constraint
without rewriting historical rows.

**Consequences:** Identical writes are idempotent, later re-observation retains
full provenance and genuine fact changes do not overwrite history. UUIDv5 and
SHA-256 content identities, exact cache bytes, compatibility and retrieval-time
leakage boundaries remain intact. The design remains provider-neutral and does
not ingest squads or players, import artifacts, access the sealed target,
promote a model, add APIs or change simulation behavior.

## ADR-039 — Reviewed current squads and offline response recordings

**Status:** Accepted

**Context:** Optional player and squad data introduces identity ambiguity,
transfer/loan chronology and a risk of allowing post-cutoff membership into
features. Provider contracts also need reproducible verification before any
vendor parser or live endpoint is selected.

**Decision:** Extend the provider-neutral manifest with optional player and
squad capabilities and distinct provider player/squad identifiers. Resolve a
player only from a reviewed exact external ID or normalized exact alias; reject
unknown, duplicate or conflicting evidence and prohibit fuzzy matching.

Represent squad membership with explicit effective and registration windows,
an as-of date and an exact loan parent when applicable. Persist only complete
simultaneous 20-team snapshots with one active registration per player. Derive
canonical squad UUIDs from competition, season and canonical team. Bind player
observations and squad snapshots to exact cached responses and use response
retrieval as their conservative knowledge cutoff. Repeat all completeness,
ordering, provenance and chronology checks in deferred PostgreSQL validation.

Add a synthetic credential-free recording for every declared capability. A
strict canonical-order manifest binds safe relative paths, canonical request
identity, exact response checksum, compatibility, timestamps, pagination,
quota and media metadata. Offline replay returns the existing typed capture and
fails on any drift. The recordings are contract evidence, not a provider
selection or vendor parser.

Keep player descriptive metadata outside the approved predictor schema unless
a later version is explicitly reviewed. Shirt number, response-only fields and
betting odds are prohibited. Squad membership can affect only later fixture
batches after separate feature work.

**Consequences:** Current match synchronization remains independent of optional
player feeds. Transfers and loans retain point-in-time provenance without
overwriting identity or history and all seven boundaries can be tested without
network access or credentials. Revision `f0006_step_6_8` becomes the migration
head; Step 6.9 needs no schema. No production provider, artifact import,
final-test access, active model, prediction lifecycle, API, deployment,
frontend or CI/CD behavior is introduced.
