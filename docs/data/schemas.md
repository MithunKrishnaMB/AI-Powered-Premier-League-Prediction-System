# Data Schemas

The data pipeline uses five deliberately separate representations.

## Raw source file

The downloaded CSV is immutable and retains all provider columns. Integrity is
established by the tracked manifest before parsing.

## Football-Data source model

`FootballDataMatch` parses the provider's abbreviated columns into typed fields.
It validates dates, scores, result codes, non-negative match statistics and row
identity. Odds and other columns that are not yet modeled remain available in
`additional_fields`; retaining a field does not make it an eligible ML feature.

Dates and times remain source-local at this boundary. Football-Data's English
match time is interpreted in the `Europe/London` timezone only when a canonical
fixture is created.

## Current-provider boundary

Step 6.1 adds a separate provider-neutral, schema-version-1 boundary for
current-season teams, fixtures, fixture status, completed results and standings.
It does not choose a provider or parse a provider-specific response.

Provider competition, season, team and fixture IDs are distinct immutable types
identified by source and opaque external ID. `CurrentSeasonScope` carries both
the expected canonical competition/season and explicit provider scope. Provider
IDs never replace canonical team or fixture UUIDs. Team resolution requires a
reviewed exact alias or external-ID mapping; unknown identities fail and fuzzy
matching is prohibited.

Provider fixture observations are score-free. Status observations are also
score-free. Only `CompletedFixtureResult`, whose status is fixed to `finished`,
accepts an official full-time score and matching outcome. `cancelled` and
`abandoned` are distinct non-completions and cannot carry canonical result data.
A postponed fixture retains its provider ID and, after explicit team resolution,
the existing stable canonical fixture UUID while kickoff and status become a new
revision.

All instants are timezone-aware UTC. Provider kickoffs also retain an IANA
source timezone, source-local date and `exact` or `date_only` precision.
Date-only values use local noon only as a deterministic anchor. If one fixture
on a source-local date is date-only, the complete date remains a simultaneous
batch. Provider retrieval time is the conservative knowledge boundary for
later point-in-time processing.

Every typed response preserves exact request identity bytes, exact provider
response bytes, their independent SHA-256 values, retrieval and optional
provider-generation timestamps, compatibility versions, HTTP metadata,
pagination and quota state. Parsed observations never replace exact bytes.
Unmodeled fields, especially betting odds and bookmaker markets, are retained
only in those bytes and are prohibited from the predictor schema.

The full contract, field-governance table and provider-cache projection are in
[Current-Provider Capability and Domain Contracts](current-provider-contracts.md).

## Canonical fixture model

`Fixture` is provider-independent. It uses:

- stable canonical team UUIDs;
- a deterministic fixture UUID;
- a canonical competition and season identifier;
- timezone-aware UTC kickoff timestamps with explicit kickoff precision;
- explicit status, score, outcome, statistics and source references.

The canonical model rejects inconsistent scores, outcomes, teams, kickoff
timestamps and fixture states.

## Point-in-time feature-row model

`PointInTimeFeatureRow` schema version 2 is the provider-independent boundary
between canonical fixtures and point-in-time feature processing. It is an
immutable, strictly validated envelope with these sections:

- `id`: deterministic UUIDv5 identity for the fixture, feature cutoff,
  predictor schema, feature-row schema and canonical input dataset;
- `fixture_id`, `competition_id`, `season_id`, `home_team_id` and
  `away_team_id`: canonical domain identity, never provider aliases;
- `kickoff_at` and `kickoff_precision`: the canonical UTC kickoff boundary and
  whether the source supplied an exact time or only a date;
- `feature_cutoff_at`: the latest instant from which predictors may obtain
  information;
- `predictors`: an explicitly versioned, deterministically ordered collection
  of named pre-match scalar values;
- `training_label`: an optional, structurally separate post-match outcome and
  full-time score; and
- `provenance`: the canonical dataset identity and schema version, canonical
  fixture checksum, recursive historical-context checksum, verified raw artifact
  identity and checksum, source capture time and team and season registry
  schema versions.

Predictor values may be strict booleans, integers, finite floating-point values,
or explicit nulls. Names use canonical snake case, must be unique and sorted,
and cannot use reserved label or post-match names. The predictor container has
its own schema ID and version so later feature definitions can evolve without
silently changing a training matrix.

Representability is not feature approval. In particular, bookmaker columns
retained at the Football-Data source boundary are not approved predictors and
must not be copied into this contract. A future feature producer must populate
only predictors declared by its reviewed predictor-schema version.

The optional training label is nested outside `predictors`. Its outcome must
agree with its non-negative full-time score. An unlabeled row is therefore
representable without using sentinel target values and downstream training
code can select labels without exposing them as predictors.

All contract timestamps are timezone-aware UTC. For an exact kickoff, the
feature cutoff may equal but cannot follow kickoff. For `date_only` fixtures,
the cutoff must precede midnight at the start of the source-local fixture date
in `Europe/London`, converted to UTC. This deliberately conservative boundary
prevents the noon anchor from implying an observed within-day order and remains
correct across daylight saving transitions. Chronological processing treats
every fixture on a local date containing a date-only record as one simultaneous
batch, calculates all rows from pre-batch state and updates state only after
the full batch.

The feature-row contract and calculator do not read raw provider files. Feature
materialization must start from canonical datasets produced only after raw
manifest verification and must carry their recorded checksums into provenance.

The predictor schema and calculation semantics are documented in
[Point-in-Time Feature Processing](../features/point-in-time.md).

## Processed feature dataset

Each completed season materializes as deterministic JSON Lines at
`data/processed/features/epl/<season>/features.jsonl` with an adjacent
`dataset-manifest.json`. The manifest pins the feature dataset and feature-row
schema version 2; predictor schema version 2 and its ordered 175-name checksum;
the feature-file count and checksum; chronology, opening-prior and Elo
semantics; the recursive historical-context checksum; canonical fixture lineage;
registry versions; and verified raw artifact lineage.

The materializer invokes checksum-verifying canonical materialization before
reading each canonical input, validates the canonical file against its own
manifest and publishes generated outputs atomically. A later season is rebuilt
only after every required predecessor is verified and processed, so its opening
prior and Elo state are traceable. Equivalent inputs produce identical bytes and
checksums. Processed feature files remain ignored generated artifacts.

## Reproducible training dataset

`TrainingExample` schema version 1 is the model-ready projection of a verified
feature row. It retains fixture, competition, season and canonical team
identity; kickoff, kickoff precision and feature cutoff; the complete versioned
predictor set; a required, structurally separate `target`; the source feature-row
ID; and the source feature-dataset ID. Its deterministic UUIDv5 binds the
example to the feature row and source feature dataset.

`plp-materialize-training` verifies and rebuilds every manifest-listed feature
season before combining them. It writes deterministic JSON Lines to
`data/processed/training/epl/2015-2016_to_2025-2026/training.jsonl` with an
adjacent versioned manifest. The manifest pins:

- the training row count and file SHA-256;
- the ordered season window and serialization order;
- the full predictor schema and the separate result/score target schema;
- the historical manifest, team registry and season registry checksums; and
- every source feature dataset and manifest checksum plus its canonical and raw
  lineage and historical-context checksum.

The loader rejects modified bytes, wrong row counts, predictor-schema drift,
unknown or cross-season feature references and incomplete season coverage.
The artifact contains all 4,180 completed fixtures and the 175 predictors in
schema version 2. Downstream model evaluation must load it through the typed
checksum validator and select only explicit chronological windows.

## Probabilistic development evaluation

Steps 3.1 through 3.8 materialize target-free `ProbabilisticPrediction` schema
version 1 rows beneath `data/processed/evaluation/epl/`. Each row contains the
deterministic prediction ID, method and partition identity, source training
dataset and example identity, canonical fixture and season identity, kickoff and
feature cutoff and three explicit probabilities in the fixed order `home_win`,
`draw`, `away_win`. A CatBoost prediction also carries its reviewed
`configuration_id`. Scores and observed outcomes are deliberately absent.

The adjacent evaluation dataset manifest pins the prediction bytes and count;
the complete verified training manifest and its checksum; benchmark, metric,
preprocessing, optimizer and numerical-runtime versions; the fixed holdout and
five expanding walk-forward folds; per-fold fit diagnostics and metrics; and
aggregate walk-forward metrics. The embedded training manifest preserves the
raw, canonical, feature, registry and recursive historical-context provenance.
Equivalent inputs produce identical prediction and manifest bytes.

### Untouched test freeze

`UntouchedTestFreeze` schema version 1 designates only 2025–26. Its deterministic
manifest contains the 380-row count, stable competition and season identity,
source training dataset and manifest checksums, a checksum of ordered target-free
example identities and explicit policies prohibiting target access before the
one-time final evaluation and prohibiting all development use. Each identity
hash input includes the immutable example, feature-row and fixture IDs, cutoff,
kickoff, season, source feature dataset and a checksum of the complete predictor
payload. It never includes an outcome, score or aggregate target statistic.

The canonical artifact is
`data/processed/evaluation/epl/test-2025-2026/freeze-manifest.json`. Strict typed
loading rejects extra fields, unsupported season boundaries and non-canonical
bytes.

### CatBoost tuning dataset

`CatBoostTuningDatasetManifest` schema version 1 records the pinned CatBoost
runtime and determinism settings, the exact ordered candidate set, all five
chronological fold definitions, fit diagnostics and probabilistic metrics,
the deterministic selection rule, the selected candidate, the final
development-only fit diagnostics, the complete embedded training manifest and
the embedded untouched-test freeze with both manifest checksums.

Only the selected candidate's 1,900 target-free fold predictions are written to
`data/processed/evaluation/epl/catboost-tuning-2015-2016_to_2024-2025/`.
Prediction ordering is partition, feature cutoff, kickoff and training-example
ID. Validation rejects candidate drift, an incorrect winner, incomplete fold or
prediction populations, cross-candidate predictions, checksum changes and test
season rows. Model weights and test predictions are not part of this schema.

### Advanced probabilistic and score-model evaluation

`AdvancedEvaluationManifest` schema version 1 pins the complete verified
training manifest and checksum plus the selected CatBoost tuning dataset,
prediction and untouched-test freeze checksums. It records four expanding
prior-out-of-fold temperature-calibration folds, five Poisson and Dixon–Coles
folds, typed optimizer and low-score-adjustment contracts, per-fold and
aggregate metrics and final development-only fit diagnostics.

The adjacent `predictions.jsonl` contains 1,520 temperature-scaling assessment
rows and 1,900 rows each for independent Poisson and Dixon–Coles. Every row uses
the shared target-free prediction schema with three explicit outcome
probabilities and immutable training-example lineage. Outcomes, goals and
expected-goal parameters are not persisted in prediction rows; score grids are
produced in memory and projected to the three-way evaluation boundary. The
manifest may contain aggregate development target counts inside metric reports,
but contains no untouched-test targets or metrics.

Rows are ordered by method, partition, feature cutoff, kickoff and training
example. The loader rejects modified or non-canonical bytes, checksum changes,
duplicate identities, unknown methods or folds, wrong method populations,
changed training lineage and any 2025–26 prediction. Artifacts are written to
`data/processed/evaluation/epl/advanced-development-2015-2016_to_2024-2025/`.

### Model assessment manifest

`ModelAssessmentManifest` schema version 1 is a single canonical JSON report for
Steps 3.9 and 3.10. It pins the complete training manifest and the checksums of
the base evaluation, selected CatBoost, advanced evaluation and untouched-test
freeze artifacts. It contains no model binary, registry state, test prediction
or test metric.

The acceptance section fixes the five evaluation seasons from 2020–21 through
2024–25, the naive baseline, all candidate aggregate and fold metrics, every
derived gate decision and the deterministic champion. Validation recomputes
coverage, relative log-loss improvement, Brier and RPS non-inferiority,
fold-level wins and champion selection rather than trusting serialized flags.

The explanation section contains a final 3,800-row development naive prior;
the documented Elo bridge signals; standardized three-class logistic
coefficients; normalized CatBoost `PredictionValuesChange` importances; global
Poisson intercept and home advantage plus attack and defence coefficients keyed
only by canonical team UUID; and final Dixon–Coles rho with its four adjusted
score cells. These are global model-structure summaries, not fixture-level or
causal explanations. The canonical path is
`data/processed/evaluation/epl/model-assessment-2015-2016_to_2024-2025/assessment-manifest.json`.

## Model artifact and registry

`ModelArtifactManifest` schema version 1 defines a content-addressed artifact
beneath `artifacts/models/v1/<model-id>/<artifact-id>/`. It requires exactly two
ordered components: a canonical stateless `preprocessor.json` and a canonical
CatBoost `classifier.json`. Each component has a stable UUIDv5 identity, fixed
role, relative path, format contract, byte count and SHA-256. Separate UUIDv5
values identify the semantic fitted model, exact component bundle and complete
manifest.

The manifest pins CPython, CatBoost, NumPy, Pydantic, tzdata and float64
requirements; the exact predictor schema, order and checksum; the fixed
home-win, draw, away-win output order; CatBoost depth-6 metadata; identity
calibration; and the explicit absence of a selected score model. Its provenance
embeds the complete training, assessment and untouched-test-freeze manifests and
cross-checks all base, CatBoost and advanced evaluation checksums.

Registry schema version 1 stores one immutable `RegistryEntry` plus canonical,
checksum-linked `RegistryEvent` files. Registration creates `candidate`; the
verified development policy may become `development_accepted`; eligible entries
may be rejected. Active promotion is unavailable without a future typed final-
test evidence contract. Registry state is not stored in the artifact manifest.

See [Model Artifacts and Registry](../models/model-artifacts.md) for byte,
identity, path, compatibility and transition rules.

## Simulation domain

Simulation schema version 1 defines strict `Scoreline`,
`ScorelineProbability`, `FixtureScorelineDistribution`, `SimulationFixture`,
`PlayedFixture`, `SampledFixtureResult`, `SeasonSimulationInput`,
`LeagueTableState` and ranked-table contracts. Distribution and sampled-result
identities are deterministic UUIDv5 values bound to their complete semantic
inputs. Scores are bounded to 0–40 and positive ordered probability mass must
sum to one within `1e-12`.

Season inputs require 20 unique, canonically ordered team UUIDs. Completed and
remaining fixture identities are unique and disjoint; all teams must belong to
the season. Date-only fixtures preserve the existing simultaneous calendar-date
batch policy. Table rows are reconciled against a canonical fixture ledger and
ranking exposes head-to-head points and away-goal values when those official
tiebreaks are used. No simulation contract accepts team names, betting odds,
training targets or a three-way-to-scoreline conversion.

`VectorizedSimulationResult` retains read-only `int64` points, goals-for and
goals-against matrices, `int16` sampled-score matrices and a float64
`(10000, 20, 20)` position-mass tensor. Its deterministic run UUID binds the
complete season input, ordered distribution identities, seed, algorithm version
and fixed count. `SeasonSimulationSummary` contains 20 ordered
`TeamSimulationSummary` records with expected points and goals, a complete
20-position probability vector and champion, top-four, top-six and relegation
probabilities. The summary UUID binds the exact aggregate content.

See [Simulation Domain, Scorelines and Table Rules](../simulation/domain-and-table.md)
for sampling, ordering and ranking details.

## PostgreSQL persistence projection

Step 5.1 finalizes the relational projection of these contracts in the
[PostgreSQL entity-relationship model](../architecture/postgresql-entity-relationship-model.md).
The projection is lossless: normalized rows support queries, while the exact
raw, canonical JSON Lines, processed JSON Lines and manifest bytes remain
independently stored and checksum-addressed. PostgreSQL `jsonb` is not used as a
replacement for canonical bytes.

Existing UUIDv5, textual dataset IDs and content checksums remain primary keys.
Owner-plus-ordinal composite keys preserve source, season, predictor, fixture,
component, registry-event and simulation order; the database never invents
surrogate identities for these records. Stable fixtures are separated from
immutable dataset-owned revisions so postponement or rescheduling cannot
overwrite a historical observation.

Predictor values retain their strict null, boolean, integer or float64 type and
remain separate from feature labels and training targets. Evaluation
predictions remain target-free and keep three explicit float64 probabilities in
the fixed `home_win`, `draw`, `away_win` order. The untouched-test freeze has a
target-free member projection and no target, score or metric fields.

Immediate constraints reject invalid ranges, states, dtypes, identities,
foreign keys and local inconsistencies. Deferred constraints reject incomplete
season membership, gaps or reordered records, predictor populations,
chronology violations, registry checksum-chain errors and incomplete
probability mass. All provenance-bearing records are immutable and every
foreign key uses restrictive deletion.

## Team identity

`data/reference/teams.json` contains 34 stable team records covering every club
in the historical window, with explicit aliases per source. Resolution
normalizes Unicode, capitalization and redundant whitespace, but deliberately
avoids fuzzy matching. A new or changed provider name must be reviewed and added
to the registry rather than guessed.

## Season membership and transitions

`data/reference/seasons.json` records the 20 canonical teams participating in
each season from 2015–16 through 2025–26 and marks the three promoted clubs with
their previous competition. This keeps promotion status point-in-time correct
instead of inferring it later from a final league table.

## Canonical interim dataset

The materializer parses and canonicalizes a manifest entry, runs competition-wide
quality checks and writes deterministically ordered JSON Lines to
`data/interim/canonical/epl/<season>/fixtures.jsonl`. A generated companion
manifest records:

- canonical dataset schema version
- source file ID, capture timestamp and checksum
- team and season registry schema versions
- fixture count and output checksum

The interim dataset is reproducible and ignored by Git. Re-running the pipeline
with unchanged inputs produces the same bytes and returns `already_current`.

## Missing and postponed data policy

- Date, teams, full-time score and result are mandatory for completed historical
  rows; malformed values fail parsing.
- Half-time values, referee and match statistics are nullable so older schemas
  can be represented without fabricated values.
- When only a date is available, canonicalization sets `kickoff_precision` to
  `date_only` and anchors the UTC timestamp at noon Europe/London. Later
  point-in-time processing must treat all date-only matches on the same date as
  a batch, not infer an ordering from the anchor.
- Unavailable optional statistics generate quality warnings, not invented zeros.
- A postponed fixture retains its stable identity based on competition, season,
  home team and away team. Its status and kickoff can be revised when a provider
  supplies the rescheduled time.
- Completed-season datasets cannot contain scheduled, postponed, cancelled or
  in-progress fixtures.

## Competition-wide quality rules

For a completed 20-team Premier League season, validation requires 380 fixtures,
unique fixture IDs, unique ordered home/away pairings, registered teams, in-season
kickoff dates, final statuses and 19 home plus 19 away fixtures per club.
