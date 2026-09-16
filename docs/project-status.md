# Project Status

**Status date:** 2026-09-16

**Runtime:** 64-bit Python 3.14.7

**Completed milestones:** A — Repository Foundation; B — Historical Data
System; C — Point-in-Time Features and Elo; D — Probabilistic Models; E —
Registry and Simulation; F — PostgreSQL Persistence; G — Current-Season
Integration; H — Prediction Lifecycle

**Current milestone:** I — FastAPI (in progress)

**Completed Milestone I steps:** 8.1 — explicit application factory, liveness
and fail-closed dependency readiness; 8.2 — request IDs, uniform error envelopes
and reusable offset-pagination contracts

**Completed Milestone H steps:** 7.1 — deterministic read-only active-model
resolution and complete registry-to-runtime artifact loading; 7.2 — unlabeled
current-evidence upcoming features; 7.3 — immutable active-model predictions;
7.4 — completed-result prediction evaluation; 7.5 — exactly-once operational
team-state and Elo advancement; 7.6 — affected future-prediction regeneration;
7.7 — provenance-bound season-simulation regeneration; 7.8 — deterministic
append-only post-match orchestration; 7.9 — recovery and partial-failure
verification

**Completed Milestone G steps:** 6.1 — current-provider capability and
provider-neutral domain contracts; 6.2 — fixture/team transformation; 6.3 —
quota, retry, authentication and sanitized transport; 6.4 — PostgreSQL exact
response caching; 6.5 — idempotent fixture synchronization; 6.6 — completed
result reconciliation; 6.7 — standings synchronization; 6.8 — reviewed current
players and simultaneous squad snapshots; 6.9 — offline exact-byte recorded
response contract tests

**Completed Milestone F steps:** 5.1 — PostgreSQL entity-relationship model
finalized against produced data and artifacts; 5.2 — typed, isolated local/test
PostgreSQL connections; 5.3 — secret-free Alembic initialization without a
schema revision; 5.4 — exact-content, identity, season and fixture migration;
5.5 — feature/Elo, model artifact and registry migration; 5.6 — training,
sealed-test, prediction and evaluation migration; 5.7 — ingestion/cache,
explicit scoreline-distribution and simulation migration; 5.8 — typed,
raw-manifest-gated immutable aggregate repositories; 5.9 — PostgreSQL
transaction, rollback, idempotency and constraint integration tests

**Completed Milestone E steps:** 4.1 — deterministic model artifact layout and
manifest; 4.2 — canonical model serialization, checksums and reload; 4.3 —
append-only registry states and development-promotion rules; 4.4 — simulator
domain contracts; 4.5 — deterministic scoreline sampling; 4.6 — immutable
table updates and ranking; 4.7 — vectorized 10,000-run execution; 4.8 —
aggregate position and threshold probabilities; 4.9 — simulator invariants and
exact reproducibility tests

**Completed Milestone D steps:** 3.1 — naive and Elo benchmarks; 3.2 —
multinomial logistic regression; 3.3 — expanding walk-forward validation; 3.4
— untouched test freeze; 3.5 — development-only CatBoost tuning; 3.6 —
chronological calibration assessment; 3.7 — independent-Poisson score baseline;
3.8 — Dixon–Coles adjustment; 3.9 — frozen development acceptance gates; 3.10
— deterministic model-appropriate global explanations

**Exact next implementation step:** 8.3 — implement read-only teams and seasons
endpoints, subject to explicit user approval.

**Milestone D closeout commit:** `3ac10a2` — complete milestone D model
acceptance and explanations

**Milestone F closeout commit:** `22e595a` — complete PostgreSQL repositories
and transaction verification

**Milestone G implementation commit:** `f34c349` — complete current-season
integration

**Milestone H implementation commit:** `4b44fcd` — add resumable idempotent
post-match workflow journal

## Implemented capabilities

- Installable `pl_platform` package using the `src/` layout.
- Explicit FastAPI application construction without an import-time application,
  startup connection or model load.
- Process-only liveness and ordered fail-closed readiness over the explicitly
  selected PostgreSQL target, exact Alembic head and strict active-model chain.
- Validated/generated request IDs, sanitized uniform error envelopes and strict
  offset-pagination contracts with deterministic navigation arithmetic.
- Typed, immutable environment configuration.
- Secret-backed, explicitly isolated PostgreSQL development/test connection
  settings and a read-only compatibility and privilege checker.
- URL-free Alembic environment with nine linear transactional revisions and
  head `f0009_step_7_9`.
- PostgreSQL checked domains, exact-byte SHA-256 verification, application
  UUIDv5 checks, restrictive provenance foreign keys, deferred aggregate
  validation and immutable update/delete guards.
- Relational structures for identity, canonical fixtures, point-in-time
  features/Elo, training/evaluation artifacts, model components, append-only
  registry events, raw captures, explicit scoreline distributions and complete
  10,000-run simulation outputs.
- Frozen aggregate write plans with explicit table ownership, caller-supplied
  identities, dependency ordering and exact canonical or binary objects.
- Pre-transaction verification of every reviewed raw capture, serializable
  exact-byte-first writes, forced deferred constraints and reload comparison.
- Stable non-secret repository failure categories, retry idempotency and
  rollback on any conflict or invalid later projection.
- Strict provider-neutral current-season team, fixture, status, completed-result
  and standings observations with external identities kept separate from
  canonical platform identities.
- Complete capability declarations separating required/optional operations from
  supported, unsupported and temporarily unavailable provider state.
- Deterministic credential-free request identity, exact provider response bytes
  and checksums, typed pagination/quota/compatibility metadata and sanitized
  provider error vocabulary.
- Explicit abandonment and completion semantics, fail-closed score/standing
  reconciliation and retrieval-time knowledge boundaries.
- Reviewed external-ID or alias resolution with disagreement rejection, stable
  historical/current fixture UUID derivation and provider-local simultaneous
  fixture batches.
- Credential-free HTTPS endpoint specifications, secret-header authentication,
  disabled redirects, bounded response sizes, deterministic bounded retries,
  process-local quota gating and URL/credential-free failure logs.
- Raw-manifest-gated provider-cache writes and latest-fresh reads that preserve
  exact request and response bytes, independent checksums, retrieval/expiry,
  compatibility and HTTP metadata.
- Immutable content-derived current fixture revisions, separate provider
  references and response observations, with fail-closed chronology and
  provider-local simultaneous batches.
- One official result per canonical fixture, repeatable exact-response
  provenance and completion/status consistency checks.
- Complete 20-team standings snapshots reconciled against results known at the
  standings retrieval boundary, with separate provider-team references.
- Provider-neutral optional player and squad capabilities with source-scoped
  external identities, reviewed exact player mappings, explicit registration,
  transfer and loan windows and complete simultaneous 20-team snapshots.
- Immutable current player observations and squad snapshots with deterministic
  UUID/content identities, exact cached-response provenance and deferred
  PostgreSQL completeness and chronology guards.
- Unlabeled upcoming-feature rows that replay only official results known before
  each current fixture batch, preserve whole-date simultaneity and retain exact
  fixture, cache, state, opening-prior, Elo and predictor provenance.
- Immutable three-way CatBoost predictions bound to exactly one active registry
  head and the complete feature/model/artifact chain. Development acceptance is
  not sufficient and the actual registry therefore produces no predictions.
- Immutable completed-prediction evaluations matched to official result
  observations, with natural-log loss, multiclass Brier and normalized ranked
  probability scores validated in both typed code and PostgreSQL.
- Append-only operational team state retaining the full official-result ledger,
  20 ordered Elo values and immutable pre/post advancement lineage. Results and
  evaluations can be applied only once and a state predecessor cannot fork.
- Affected future predictions regenerated from refreshed evidence as new
  immutable feature/prediction pairs with explicit supersession lineage.
- Deterministic season-simulation regeneration from independently approved
  explicit scoreline distributions, preserving canonical input, all six exact
  NumPy components, complete aggregate summary and prior/replacement run
  lineage without converting CatBoost probabilities to scorelines.
- Canonical post-match workflow manifests and six hash-linked append-only
  checkpoints composing evaluation, state advancement, prediction regeneration
  and simulation regeneration. Recovery verifies the persisted prefix and
  resumes only its missing suffix without a mutable workflow-status pointer.
- A synthetic credential-free recorded-response corpus covering all seven
  capabilities and replay validation for exact bytes, checksums, request
  identity, compatibility, retrieval time, pagination and quota metadata.
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
- Versioned, content-addressed model layout with distinct stable model,
  component, artifact and manifest UUIDv5 identities.
- Strict manifest contracts for runtime, predictor, outcome, classifier,
  preprocessing, calibration, absent-score-model and provenance metadata.
- Canonical CatBoost JSON serialization with volatile metadata normalized,
  exact component checksums and float64-tolerance development round-trip checks.
- Deterministic loading that rejects non-canonical bytes, missing or changed
  components, incompatible runtimes and predictor or policy drift.
- Append-only registry entries and checksum-linked events with deterministic
  candidate and development-accepted transitions.
- Fail-closed active promotion until a future typed, explicitly authorized
  one-time final-test evidence contract exists.
- Deterministic read-only registry enumeration with state derived only from the
  complete canonical event history and no mutable active pointer.
- Exactly-one active-model resolution with stable failures for absent or
  ambiguous active state, malformed history, missing or changed artifacts,
  incompatible schemas or runtimes, unsupported components and provenance
  drift.
- Complete registry-to-artifact loading that rechecks manifest identity and
  checksum, canonical component bytes, CatBoost depth 6, stateless
  preprocessing, identity calibration, 175 predictors and fixed home/draw/away
  outcome order before returning the model.
- Strict version-1 simulator contracts for canonical 20-team inputs, explicit
  scoreline distributions, sampled results and immutable table state.
- Date-only simulation fixtures conservatively batched with every fixture on
  the same Premier League calendar date.
- Stateless SHA-256 scoreline draws keyed by seed, simulation index and fixture
  UUID, with canonical inverse-CDF selection independent of iteration order.
- Immutable fixture-ledger table updates with exact result, goal and points
  reconciliation.
- Final-table ranking by points, goal difference, goals scored, head-to-head
  points and head-to-head away goals, with unresolved playoffs failing closed.
- Fixed 10,000-run simulation batches with vectorized score selection, goal and
  point accumulation and read-only NumPy result matrices.
- Deterministic simulation identities binding the complete canonical season
  input, score-distribution identities, seed, run count and algorithm version.
- Doubly stochastic final-position mass, using equal fractional allocation over
  statistically unresolved playoff slots without asserting an official winner.
- Per-team expected points, goals and goal difference; all 20 position
  probabilities; and champion, top-four, top-six and relegation probabilities.
- Content-derived aggregate summary identities and league-wide unit-mass,
  threshold-total, conservation and reproducibility invariants.
- PostgreSQL-aligned entity-relationship model covering exact artifact bytes,
  stable identities, canonical fixture revisions, point-in-time features,
  training/evaluation lineage, semantic and physical model records,
  append-only registry events, explicit distribution provenance, deterministic
  simulation inputs/runs and complete aggregate summaries.
- Explicit persistence ownership, primary and foreign keys, uniqueness,
  canonical order, immutability, restrictive deletion and fail-closed immediate
  and deferred constraint responsibilities enforced by migrations and the
  repository transaction boundary.

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
- Model ID: `ca224b48-24c9-54f2-9df7-28f293ae426b`.
- Artifact ID: `a5f8a12c-768b-5b5f-a8af-53dae5e5505e`.
- Artifact manifest ID: `5e94e19e-d4bc-540c-9b04-dd245f5a3073`.
- Artifact manifest SHA-256:
  `53090c8956291926b03a0009695193638919c5a289afe646accee03ad43f22a3`.
- Preprocessor SHA-256:
  `6984224e6ba51551b59d110e87b5c37da158cb04d8877a3b1f5e4b60f094bba7`.
- Classifier SHA-256:
  `f2e273bf9dd0c6ad9897637ba73546988842a4a7f133ad7a9a581a1dacd005c7`.
- Registry entry ID: `86374a5a-2317-51e3-8ba1-e156d8810640`.
- Registry state: `development_accepted`; no active model exists.
- Raw, interim and processed files are reproducible local artifacts and are
  ignored by Git.

## Last verified quality result

The implementation through Step 8.2 passes the complete local suite:

- Runtime: 64-bit Python 3.14.7.
- pytest: 543 passed, including side-effect-free factory construction,
  process-only liveness, dependency readiness, request-ID/error/pagination
  contracts, actual no-active registry behavior and the complete prior suite.
- Branch coverage: 90.37%, above the required 90% threshold.
- Ruff format and lint: passed.
- Strict mypy: passed across all 190 source, test and migration Python files.
- Dependency consistency: passed.
- Development and test databases are at exact head `f0009_step_7_9`; the test
  database completed an `f0009` to `f0008` downgrade and re-upgrade while the
  two targets remained explicitly isolated.
- All 11 historical raw captures passed manifest verification with manifest
  SHA-256 `87b599ecb06e5f00e64323ef4b426b1b2d2f7db803e26038ae9fb4a76da96aa1`.
- No external provider was selected or contacted. Only synthetic exact bytes
  were persisted to the isolated test database; no production artifact import,
  final-test access or model activation occurred. The actual filesystem
  registry returned `no_active_model`; registry and model corpus aggregate
  hashes remained byte-identical. No changes were staged or committed.

The preserved Milestone F closeout result was:

- pytest: 389 passed, including live PostgreSQL migration and repository
  transaction checks.
- branch-aware coverage: 90.53% (minimum required: 90%).
- Ruff lint: passed.
- Ruff format check: passed.
- strict mypy: passed.
- package dependency check: passed.
- documentation diff check: passed with no whitespace errors.
- all local Markdown links resolve.
- development and test connectivity checks reported PostgreSQL 18.4, `pl_app`,
  UTC and the exact `pl_platform_dev` and `pl_platform_test` database names.
- the application role is a login without superuser, database-creation,
  role-creation, replication or row-security-bypass capability.
- the test database completed a transactional upgrade from base to
  `f0004_step_5_7`, downgrade to base and second upgrade to head.
- repository tests verified atomic exact-object and normalized-row writes,
  identical retry idempotency, conflict detection and reload comparison.
- a later normalized-row constraint failure rolled back the earlier exact-byte
  insert, while a raw-manifest failure prevented any database write.
- direct checksum corruption and immutable-row updates were rejected by
  PostgreSQL.
- schema introspection confirmed all 11 bounded application schemas, restrictive
  update/delete behavior on every provenance foreign key, immutable guards on
  every application table and the sealed-test and 10,000-run constraints.
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
- the selected CatBoost model was serialized, checksum-verified, reloaded and
  compared across all 3,800 development rows without accessing 2025–26 targets.
- the artifact was registered through two immutable events as candidate and
  development-accepted; active promotion remains unavailable.
- simulation fixtures reproduced the same sampled result independently of
  fixture iteration order and date-only records absorbed all fixtures on their
  Premier League calendar date into one simultaneous batch.
- table tests reconciled home wins, draws and away wins against the immutable
  fixture ledger and exercised every official statistical ranking criterion;
  an unresolved playoff remained an explicit failure.
- repeated 10,000-run batches produced identical identities and exact NumPy
  matrices; team and position mass each summed to one for every run.
- aggregate champion, top-four, top-six and relegation probability totals were
  exactly one, four, six and three within the strict numerical tolerance.
- a complete deterministic 380-fixture double round robin produced 57 points,
  19 goals for and 19 goals against per club in every run and conserved 1,140
  league points per simulation.

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
- The selected development policy remains CatBoost depth 6 with identity
  calibration and outcome order `home_win`, `draw`, `away_win`.
- A `development_accepted` registry entry is not an active model. Active
  promotion remains unavailable until typed final-test evidence is authorized
  and implemented.
- The three-way classifier does not produce scoreline probabilities. Simulation
  requires an explicit, separately identified scoreline distribution.
- Preserve deterministic identities, canonical ordering and bytes, checksums,
  numerical dtypes and the complete source-to-evaluation provenance chain.
- Develop the backend and ML system before the frontend.

## Not implemented yet

- Final one-time untouched-test evaluation.
- Production current-provider integration for fixture score distributions and
  current-season simulation runs.
- Final-test evidence and active model promotion.
- Production artifact-corpus import through the typed repositories.
- A selected production current-data provider and its vendor-specific parsers.
- Teams, seasons and every later football-domain FastAPI endpoint.
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

Steps 7.1 through 7.9 and Milestone H are complete. The actual registry still
has no active model, so no real current prediction or derived simulation corpus
exists. The post-match workflow now binds every immutable child under one
deterministic manifest and derives progress from a hash-linked event prefix.
Retries resume only the missing suffix; committed child writes and checkpoint
acknowledgement loss are safe. Milestone I now has the Step 8.1 application and
health boundary plus the Step 8.2 transport contracts. The exact next boundary
is Step 8.3, read-only teams and seasons endpoints using those shared contracts.
