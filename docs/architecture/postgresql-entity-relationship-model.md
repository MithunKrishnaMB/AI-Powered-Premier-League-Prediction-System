# PostgreSQL Entity-Relationship Model

**Implementation status:** The model is implemented by the linear Step
5.4–5.7 Alembic chain ending at revision `f0004_step_5_7` and Steps 5.8–5.9
provide and verify its typed transaction boundary. No production artifact
corpus has been imported by the migrations or repository tests.

## Status and scope

This document is the normative Step 5.1 persistence design for the data and
artifacts implemented through Milestone E. It finalizes PostgreSQL entities,
ownership, keys, relationships, ordering, lifecycle rules and fail-closed
constraints without configuring or connecting to a database.

The design covers:

- source manifests and immutable raw captures;
- versioned reference registries, canonical teams and season membership;
- canonical fixture datasets and fixture revisions;
- point-in-time feature and Elo artifacts;
- training examples and structurally separate targets;
- target-free development predictions, evaluations and the untouched-test
  freeze;
- semantic models, artifact manifests and physical components;
- append-only registry entries and events;
- explicit fixture scoreline distributions and their provenance;
- deterministic 10,000-run simulation inputs, results and aggregate summaries.

Database settings, credentials and connections begin in Step 5.2. Alembic
initialization is Step 5.3. This document remains the normative design rather
than a migration; the implementation and repository behavior are documented in
the linked PostgreSQL architecture pages.

## Verified design baseline

The schema is designed against the produced artifacts, not an imagined future
shape:

- 11 immutable Football-Data captures and canonical season datasets contain
  4,180 fixtures from 2015–16 through 2025–26;
- 11 point-in-time feature datasets contain 4,180 schema-version-2 rows and the
  exact 175-name `epl-pre-match` predictor contract;
- one schema-version-1 training dataset contains 4,180 examples;
- development evaluation artifacts contain 7,980 base, 1,900 selected CatBoost
  and 5,320 advanced target-free prediction rows;
- `untouched-test-2025-2026-v1` freezes 380 target-free identities and the
  2025–26 target remains sealed;
- the selected semantic model is CatBoost depth 6 with identity calibration and
  outcome order `home_win`, `draw`, `away_win`;
- the physical artifact contains one stateless preprocessor and one CatBoost
  classifier component with independent UUIDv5 identities and checksums;
- registry history ends at `development_accepted`; no active model exists; and
- simulation schema and algorithm version 1 execute exactly 10,000 runs, but no
  simulation artifact has yet been written to disk or PostgreSQL.

## Relationship overview

```text
raw_capture -> canonical_dataset -> fixture_revision
                                -> feature_dataset -> feature_row
                                                   -> training_example
                                                   -> probabilistic_prediction
                                                   -> model -> model_artifact
                                                              -> component
                                                              -> registry_event

training_dataset -> untouched_test_freeze (target-free identity only)

fixture -> scoreline_distribution -> simulation_input -> simulation_run
                                              |                 |
                                              +-----------------+
                                                        -> simulation_summary
```

Arrows mean required provenance references, not permission to cascade-delete
the referenced record.

## PostgreSQL type policy

The migrations must introduce reusable checked domains or equivalent named
column constraints with these semantics:

| Logical type | PostgreSQL representation | Required constraint |
| --- | --- | --- |
| Stable UUID | `uuid` | Supplied by the domain; no database default |
| SHA-256 | `text` | Exactly 64 lowercase hexadecimal characters |
| Version | `smallint` | Strictly positive |
| Count/ordinal | `integer` or `bigint` | Non-negative or positive as declared |
| UTC instant | `timestamptz` | Canonical source bytes retain the original `Z` representation |
| Float64 | `double precision` | Reject NaN and positive/negative infinity |
| Probability | `double precision` | Finite and within `[0, 1]` |
| Positive mass | `double precision` | Finite and within `(0, 1]` |
| Unsigned 64-bit seed | `numeric(20,0)` | Between `0` and `18446744073709551615` |
| Exact artifact bytes | `bytea` | Immutable and checksum-verified |

Text discriminators use named `CHECK` constraints rather than open-ended text.
This keeps schema-version transitions explicit and avoids silently accepting a
new state, model family, dtype or serialization profile.

PostgreSQL `jsonb` is never an identity source because it does not preserve
input key order or whitespace. It may be added as a derived query projection,
but the exact `bytea` remains authoritative.

## Exact content and artifact bytes

### `lineage.stored_object`

One row represents one exact byte sequence.

| Column | Rule |
| --- | --- |
| `sha256` | Primary key; existing content checksum |
| `byte_count` | Positive `bigint`; equals `octet_length(payload)` |
| `media_type` | Required constrained text |
| `encoding` | Nullable only for binary array components |
| `format_id` | Required versioned format identifier |
| `canonicalization_profile` | `opaque`, `canonical_json_v1`, `canonical_jsonl_v1`, `identity_json_v1` or `numpy_array_v1` |
| `payload` | Exact non-null `bytea` |

The database checksum constraint must compare `sha256` with lowercase
`encode(digest(payload, 'sha256'), 'hex')`. Enabling the required PostgreSQL
digest capability belongs in a later migration, not Step 5.1.

Canonical JSON version 1 means UTF-8 without a byte-order mark, unescaped
Unicode, sorted object keys, two-space indentation, no non-finite number and
exactly one trailing line feed. Canonical JSON Lines version 1 means one
compact, key-sorted UTF-8 object per line, one final line feed and the
artifact-specific declared record order. Compact identity JSON is a hashing
input and is kept distinct from persisted pretty JSON.

Every independently traceable file has its own `stored_object` reference:
raw capture, canonical fixture JSONL, canonical manifest, feature JSONL,
feature manifest, training JSONL, training manifest, prediction JSONL,
evaluation or assessment manifest, test-freeze manifest, model manifest,
model component, registry entry and registry event. Reusing the same byte
content is allowed; collapsing the owning domain entities is not.

## Identity and reference entities

### `identity.competition`

- Primary key: `competition_id text`.
- Current required row: `eng-premier-league`.
- Referenced by seasons, fixtures, datasets, models and simulations.

### `identity.source`

- Primary key: existing `source_id text`.
- Stores provider name, HTTPS homepage, attribution and usage notice.
- `identity.source_allowed_host(source_id, ordinal)` owns the ordered, unique
  hostname allowlist.

### `identity.reference_document`

- Primary key: `document_sha256`, referencing `lineage.stored_object`.
- Alternate key: `(document_kind, schema_version, document_sha256)`.
- `document_kind` is currently `historical_manifest`, `team_registry` or
  `season_registry`.
- The checksum, rather than schema version alone, identifies a registry
  revision. Schema versions may legitimately have more than one reviewed
  content revision.

### `identity.team`

- Primary key: the existing canonical `team_id uuid`.
- The stable UUID is the only unversioned team attribute.
- `identity.team_registry_member(document_sha256, ordinal)` owns the canonical
  order and stores the referenced team, slug, display name and country code.
- Slug is unique within a team-registry document but is not the durable
  identity. Country code is constrained to three uppercase characters.
- `identity.team_alias(document_sha256, team_id, source_id, ordinal)` stores the
  reviewed external name and optional external ID.
- The normalized `(document_sha256, source_id, external_name)` is unique. There
  is no similarity field, fallback alias or fuzzy matching operation.

### `identity.season`

- Primary key: `(competition_id, season_id)`.
- `season_id` matches `YYYY-YYYY`; end year is start year plus one.
- This is the stable season identity. Versioned dates, completion status and
  membership belong to `identity.season_registry_entry`, not to an inferred
  final table.

### `identity.season_registry_entry`

- Primary key:
  `(season_registry_sha256, competition_id, season_id)`.
- Required foreign keys: season-registry reference document and stable season.
- Stores registry ordinal, start date, end date and completion status.
- Start date precedes end date and both years agree with `season_id`.

### `identity.season_membership`

- Primary key:
  `(season_registry_sha256, competition_id, season_id, team_id)`.
- Foreign keys reference the exact season-registry entry and team.
- `entry_status` is `continued` or `promoted`.
- Promoted rows require `previous_competition_id`; continued rows prohibit it.
- A deferred constraint trigger requires exactly 20 unique members and exactly
  three promoted members for every Premier League season registry revision.
- An explicit `ordinal` preserves registry order; it is unique within the exact
  owning season-registry entry.

## Ingestion and canonical fixtures

### `ingestion.raw_capture`

- Primary key: `(source_id, artifact_id)` from the historical manifest.
- Foreign keys: source, historical-manifest reference document and exact raw
  `stored_object` checksum.
- Stores source URL, destination, capture time, encoding, expected bytes,
  expected rows, required-column contract and immutable flag.
- Source URL must be HTTPS and its host must be an explicitly allowed host.
- Expected checksum and byte count must equal the referenced exact bytes.
- A provider correction creates another reviewed capture or manifest revision;
  it never updates the row or replaces bytes.

### `provider_cache.response`

Step 5.7 created this cache shape, Step 6.1 defined its provider-neutral
compatibility mapping and Step 6.4 now writes and reads it.

- Primary key: `cache_key_sha256`, deterministically derived from contract
  version, source, mapped cache capability, exact request checksum and UTC
  retrieval timestamp.
- `request_identity_sha256` references compact canonical credential-free
  request bytes in `lineage.stored_object` with profile `identity_json_v1`.
- `response_sha256` references the exact unmodified provider response body;
  parsed observations never replace it.
- `fetched_at` is the response retrieval and point-in-time knowledge boundary.
- `http_status`, `media_type`, `etag` and `last_modified` preserve transport
  metadata without storing headers or credentials.
- The response object's `format_id` pins current-provider contract, provider API
  and parser-schema compatibility. The same values are included in the exact
  request identity, so a compatibility change creates a new identity.
- `expires_at` is supplied explicitly by the Step 6.4 freshness caller, must
  remain later than `fetched_at` and is excluded at or after expiry.

The existing cache capability values map current-season teams to `metadata`,
fixtures and fixture status to `fixtures`, completed results to `results` and
standings to `standings`. The exact operation remains inside request identity,
so operations sharing a broad cache value cannot collide.

Step 6.4 writes an immutable `PROVIDER_CACHE` aggregate containing both exact
stored objects before the normalized response row. The established repository
verifies the reviewed historical raw manifest before opening its serializable
transaction, then reloads and compares every byte and projected value.

### `football.canonical_dataset`

- Primary key: `(dataset_id, manifest_sha256)`. The first component is the
  existing textual ID, such as `canonical-fixtures-2025-2026`; the second makes
  every exact manifest revision independently addressable.
- Required foreign keys: competition-season, raw capture, team-registry
  document, season-registry document, fixture JSONL object and manifest object.
- Stores dataset/schema version, fixture count and the declared ordering
  contract.
- Alternate unique keys: `(dataset_id, fixtures_sha256)` and
  `(competition_id, season_id, dataset_schema_version, fixtures_sha256)`.
- The manifest checksum and fixture-file checksum remain distinct.

### `football.fixture`

- Primary key: existing deterministic `fixture_id uuid`.
- Immutable identity columns: competition, season, home team and away team.
- Unique constraint:
  `(competition_id, season_id, home_team_id, away_team_id)`.
- Foreign keys require the stable season and both canonical teams. The exact
  membership checks occur on each fixture revision through its canonical
  dataset's season-registry document.
- Home and away teams must differ.
- Kickoff, status and result do not belong to this identity row because a
  postponed fixture keeps its fixture UUID when those facts are revised.

### `football.fixture_revision`

- Primary key: `(canonical_dataset_id, canonical_manifest_sha256, fixture_id)`.
- Owner: canonical dataset; foreign key to the stable fixture.
- Composite foreign keys require both fixture teams to be members of the exact
  season-registry revision pinned by the canonical dataset.
- `record_ordinal` is unique and gap-free within the exact dataset revision.
- Stores kickoff, precision, status, matchweek, referee, full- and half-time
  scores, outcome and nullable statistics.
- Finished fixtures require a full-time score and matching outcome. Inactive
  fixtures prohibit scores and outcomes. Half-time goals cannot exceed final
  goals. All goal and statistic counts are non-negative.
- `football.fixture_source_reference(canonical_dataset_id,
  canonical_manifest_sha256, fixture_id, ordinal)` owns the ordered source
  references and makes
  `(source_id, external_id)` unique within a revision.
- Optional statistics remain null when unavailable; null is never rewritten as
  zero.

Historical completed-season datasets additionally require 380 finished
fixtures, one ordered home/away pairing and 19 home plus 19 away appearances
per member. These are deferred database constraints because they span rows.

### `football.fixture_batch`

- Primary key:
  `(canonical_dataset_id, canonical_manifest_sha256, batch_ordinal)`.
- Kind is `date_only_date` or `exact_kickoff`.
- Stores the Europe/London competition date and, for exact batches, the exact
  UTC kickoff.
- `football.fixture_batch_member` has primary key `(canonical_dataset_id,
  canonical_manifest_sha256, batch_ordinal, member_ordinal)` and a unique
  fixture reference.
- If any fixture on a competition date has `date_only` precision, one batch
  must contain every fixture on that date, ordered by explicit ordinal derived
  from fixture UUID. Otherwise fixtures batch only by identical exact kickoff.

This persists the already implemented chronology boundary without treating the
date-only noon anchor as an actual ordering signal.

## Point-in-time features and Elo

### `feature.predictor_schema`

- Primary key: `(schema_id, schema_version)`.
- Stores count and ordered-name checksum.
- `feature.predictor_definition` has primary key
  `(schema_id, schema_version, ordinal)`, a unique name within the schema and
  gap-free ordinals.
- The version-2 contract requires `epl-pre-match`, 175 names and the exact
  existing checksum and ordering.
- Reserved post-match names and prefixes are prohibited.

### `feature.processing_policy`

- Primary key: a content checksum over the complete policy.
- Stores chronology, date-only timezone, five-match form window, opening-prior
  rules and constants and Elo version and constants.
- Version 1 requires Elo initial rating 1500, home advantage 65, K-factor 20,
  rating scale 400 and season retention 0.75.

### `feature.feature_dataset`

- Primary key: `(dataset_id, manifest_sha256)`, preserving the existing textual
  ID while retaining every exact manifest revision.
- Required foreign keys: competition-season, canonical dataset, raw capture,
  predictor schema, processing policy, feature JSONL object and manifest
  object.
- Stores feature dataset/row versions, row count, recursive historical-context
  checksum and the previous canonical dataset/checksum references when present.
- Alternate unique keys: `(dataset_id, features_sha256)` and
  `(competition_id, season_id, dataset_schema_version, features_sha256)`.
- The first tracked season requires all previous-season fields to be null;
  later seasons require all of them to be present.

### `feature.feature_row`

- Primary key: existing deterministic `feature_row_id uuid`.
- Foreign keys: exact owning feature-dataset revision and exact fixture
  revision.
- Unique constraints: `(feature_dataset_id, feature_manifest_sha256,
  fixture_id)` and `(feature_dataset_id, feature_manifest_sha256,
  record_ordinal)`.
- Stores schema version, canonical identities, kickoff, kickoff precision and
  feature cutoff.
- Exact-kickoff cutoffs may equal but cannot follow kickoff. Date-only cutoffs
  must precede local midnight at the start of the fixture date.
- The row UUID is recomputed from the exact existing identity inputs before
  insertion; a mismatch fails.

### `feature.feature_value`

- Primary key: `(feature_row_id, predictor_ordinal)`.
- Foreign key to the exact predictor definition.
- Uses `value_kind` of `null`, `boolean`, `integer` or `float64` with separate
  nullable typed columns.
- A named check requires exactly the column selected by `value_kind`; `null`
  requires all value columns to be null.
- Float values are finite `double precision`; integers remain integers rather
  than being silently coerced during persistence.
- A deferred constraint requires exactly 175 contiguous values matching the
  dataset's predictor schema.

### `feature.feature_label`

- Optional one-to-one child keyed by `feature_row_id`.
- Stores outcome and full-time score outside predictor values.
- Historical completed datasets require it; future upcoming-fixture feature
  rows may omit it.

### `feature.elo_rating_observation`

- Primary key:
  `(feature_dataset_id, feature_manifest_sha256, batch_ordinal, team_id,
  elo_schema_version)`.
- Stores the finite pre-batch rating and policy checksum.
- It is an optional normalized projection of already provenance-bound feature
  computation, not a replacement identity for the Elo predictors recorded in
  the feature artifact.
- No observation may incorporate a result from its own batch.

## Training and the sealed test boundary

### `ml.training_dataset`

- Primary key: `(dataset_id, manifest_sha256)`, preserving the existing textual
  dataset ID while retaining an exact immutable manifest revision.
- Required foreign keys: exact training JSONL and manifest objects, predictor
  schema, target schema and all three input reference-document checksums.
- Stores dataset/row versions, row count, training checksum and ordering policy.
- `ml.training_dataset_season(dataset_id, manifest_sha256, ordinal)` preserves
  the ordered season window.
- `ml.training_feature_source(dataset_id, manifest_sha256, ordinal)` links each
  exact feature dataset, feature manifest checksum, canonical dataset, raw
  capture and historical-context checksum.

### `ml.training_example`

- Primary key: existing deterministic `training_example_id uuid`.
- Required foreign key to the exact source feature row/dataset.
- Canonical identities and temporal fields are copied only as checked snapshot
  values. They must equal the referenced feature row.
- Predictors are obtained through the immutable feature row. Exact duplicated
  JSONL bytes remain available through each owning training artifact.

### `ml.training_dataset_example`

- Primary key: `(training_dataset_id, training_manifest_sha256, ordinal)`.
- Required foreign keys: exact training-dataset revision and training example.
- The example is unique within the dataset revision.
- This membership relation allows an immutable training example to appear in a
  later content-identified corpus without changing its existing UUID.

### `ml.training_target`

- Required one-to-one child keyed by `training_example_id`.
- Stores outcome, home goals and away goals separately from predictors and
  provenance.
- Outcome and score must agree.
- Database roles introduced later must keep target access separate from
  target-free prediction and simulation reads.

### `ml.untouched_test_freeze`

- Primary key: `(freeze_id, manifest_sha256)`, retaining the existing literal ID
  while independently addressing exact freeze revisions.
- Required foreign keys: source training dataset and exact freeze-manifest
  object.
- Stores status, row count, ordered target-free identity checksum, target-access
  policy and development-use policy.
- Version 1 requires only season `2025-2026`, status `frozen_untouched` and the
  two existing prohibition policies.

### `ml.untouched_test_freeze_member`

- Primary key: `(freeze_id, freeze_manifest_sha256, ordinal)`.
- Unique training-example identity within the freeze.
- Stores training-example, feature-row and fixture IDs; season; cutoff; kickoff;
  source feature dataset; and predictor-payload checksum.
- It deliberately has no target foreign key, outcome, score or metric column.
- Its canonical ordered bytes must reproduce the freeze identity checksum.

The member rows are reconstructed only through the existing target-free freeze
builder during a future verified import. Their design does not authorize final
test evaluation or target access.

## Evaluation and model-selection entities

### `ml.evaluation_dataset`

- Primary key: `(dataset_id, manifest_sha256)`, retaining the existing textual
  dataset identity and every exact immutable manifest revision.
- `evaluation_kind` is `base`, `catboost_tuning`, `advanced` or `assessment`.
- Required foreign keys: source training dataset, exact manifest object and,
  when applicable, exact prediction JSONL object.
- Stores dataset/prediction schema versions, row count, numerical-runtime
  contract and declared ordering.
- Development season and excluded season membership are stored in ordered child
  rows with roles, never inferred from prediction dates.

### `ml.evaluation_partition`

- Primary key:
  `(evaluation_dataset_id, evaluation_manifest_sha256, partition_id)`.
- Owns ordered `reference`, `evaluation` and `excluded` season members.
- Season groups must be unique and disjoint. Every reference season precedes
  every evaluation season and every evaluation season precedes every excluded
  season.
- Row counts and fit diagnostics are immutable partition metadata.

### `ml.probabilistic_prediction`

- Primary key: existing deterministic `prediction_id uuid`.
- Required foreign keys: exact owning evaluation-dataset revision, partition,
  source training-dataset revision/example and fixture.
- Unique constraint prevents duplicate method/configuration predictions for one
  source example and partition.
- Stores method, method version, optional configuration ID, cutoff, kickoff and
  three explicit `double precision` columns:
  `home_win_probability`, `draw_probability`, `away_win_probability`.
- All three values are finite and in `[0,1]`; their sum must equal one within
  `1e-12`.
- The outcome order is fixed by the evaluation dataset contract as
  `home_win`, `draw`, `away_win`.
- No target, observed score or betting-odds column is permitted.
- A development evaluation cannot contain a prediction for a season named in
  its untouched-test membership.

### `ml.evaluation_metric`

- Primary key: a SHA-256 over the complete canonical metric payload.
- A `NULLS NOT DISTINCT` unique key covers evaluation dataset revision,
  partition, method, optional configuration ID and scope.
- Stores prediction and outcome counts, mean natural-log loss, mean
  three-class Brier score and normalized ranked probability score.
- Counts and metrics are non-negative and finite; outcome counts sum to the
  prediction count.
- Metrics remain development evidence and are not registry state.

### Separate evaluation metadata

The following one-to-one or owned child tables remain distinct:

- `ml.catboost_candidate` and `ml.catboost_fold_fit` preserve each predefined
  candidate, fixed CPU/single-thread/seed contract, fold diagnostics and
  selection ordering;
- `ml.calibration_evaluation` and `ml.calibration_fold_fit` preserve the
  identity-versus-temperature comparison and selected identity strategy;
- `ml.score_model_evaluation`, `ml.poisson_fit` and `ml.dixon_coles_fit`
  preserve score-model optimizer, grid and low-score-correction metadata; and
- `ml.model_assessment` preserves frozen acceptance gates, selected champion
  and global explanation identity while linking every contributing evaluation
  artifact checksum.

These tables may reference exact manifest bytes for fields that do not require
relational querying, but classifier, preprocessing, calibration and score-model
metadata may never share a polymorphic catch-all row.

## Semantic models and physical artifacts

### `model.semantic_model`

- Primary key: existing deterministic `model_id uuid`.
- Required foreign keys: competition, training dataset, model assessment and
  untouched-test freeze.
- Stores specification version and the exact checksums used by the UUIDv5
  identity.
- A semantic model is independent of physical serialization and registry state.

### `model.classifier_specification`

- Required one-to-one child keyed by `model_id`.
- Version-1 constraints fix family `catboost_multiclass`, method version 1,
  configuration `catboost-depth6-regularized`, 200 iterations, depth 6,
  learning rate 0.05, L2 leaf regularization 10, `MultiClass`, seed 20260912,
  no bootstrap, zero random strength, symmetric trees and `Min` NaN handling.

### `model.preprocessing_specification`

- Required one-to-one child keyed by `model_id`.
- Version 1 is stateless ordered-numeric preprocessing: exact manifest order,
  booleans to 0.0/1.0, numeric values to NumPy float64, null to NaN, no learned
  imputation and no learned scaling.

### `model.calibration_specification`

- Required one-to-one child keyed by `model_id`.
- Version 1 requires identity calibration, zero parameters and no component.

### `model.score_model_specification`

- Required one-to-one child keyed by `model_id`; absence is explicit, not null.
- The current model requires status `not_included`, no component, no scoreline
  capability and reason `no_score_model_selected_for_this_artifact`.

### `model.prediction_contract`

- Required one-to-one child keyed by `model_id`.
- Fixes the task, ordered outcomes, `1e-12` probability tolerance and
  `produces_scorelines = false`.

### `model.runtime_requirement`

- Required one-to-one child keyed by `model_id`.
- Version 1 requires 64-bit CPython 3.14.7, CatBoost 1.2.10, NumPy 2.5.3,
  Pydantic 2.13.5, tzdata 2026.3, float64, CPU and one thread.
- Predictor compatibility separately references `epl-pre-match` version 2 and
  rejects unknown, missing or reordered predictors.

### `model.model_artifact`

- Primary key: existing deterministic `artifact_id uuid`.
- Required foreign key: semantic model.
- Stores layout version and ordered component-identity checksum inputs.
- One semantic model may have multiple future physical artifacts, but an exact
  component bundle has one artifact identity.

### `model.artifact_manifest`

- Primary key: existing deterministic `manifest_id uuid`.
- Required one-to-one foreign key to model artifact, plus exact manifest
  `stored_object` checksum.
- Unique constraints: artifact ID and manifest checksum.
- The external manifest checksum remains distinct because it cannot be embedded
  in its own bytes.

### `model.artifact_component`

- Primary key: existing deterministic `component_id uuid`.
- Required foreign keys: artifact and exact component `stored_object`.
- Unique constraints: `(artifact_id, ordinal)`, `(artifact_id, role)` and
  `(artifact_id, relative_path)`.
- Version 1 requires ordinal 1 `preprocessor` at
  `components/preprocessor.json` followed by ordinal 2 `classifier` at
  `components/classifier.json`.
- Role fixes format, media type, required flag, byte count and checksum.
- Absolute paths, backslashes, traversal, unknown roles and unknown files fail.

## Append-only model registry

### `registry.registry_entry`

- Primary key: existing deterministic `entry_id uuid`.
- Required one-to-one foreign keys to semantic model, artifact and artifact
  manifest.
- Stores the verified relative manifest path and checksum.
- It has no mutable `current_state` or `is_active` column.

### `registry.registry_event`

- Primary key: existing deterministic `event_id uuid`.
- Required foreign key to registry entry and exact event `stored_object`.
- Unique constraints: `(entry_id, sequence)` and event checksum.
- Stores previous event ID and declared previous-event checksum, action,
  from-state, to-state, artifact-manifest checksum, optional assessment
  checksum and optional rejection reason.
- Sequence 1 must be `register`, `NULL -> candidate`, with no previous event.
- Every later sequence must be gap-free, name the preceding event checksum and
  begin from that event's destination state.
- `accept_development` requires the exact accepted assessment checksum.
- `reject` requires a reason and is terminal.
- Assessment evidence is prohibited on other actions; rejection reasons are
  prohibited on non-rejection actions.

Registry schema version 1 reserves `active` and `retired` vocabulary but rejects
an activation event with `final_test_evidence_required`. A future migration may
enable activation only alongside a typed, explicitly authorized, one-time
final-test evidence foreign key. Development acceptance never satisfies that
condition. A future partial unique index must allow at most one active artifact
per competition, but currently there are zero.

Registry state is exposed only by a view over the last verified event. The view
does not become a stored pointer and cannot be updated.

## Explicit simulation inputs

### `simulation.scoreline_distribution`

- Primary key: existing deterministic `distribution_id uuid`.
- Required foreign key to stable fixture identity.
- Stores schema version and the fixture's home/away identities.
- The distribution UUID is recomputed from the fixture, teams and exact ordered
  mass before insertion.

### `simulation.scoreline_probability`

- Primary key: `(distribution_id, score_ordinal)`.
- Unique constraint: `(distribution_id, home_goals, away_goals)`.
- Goals are `smallint` constrained to 0–40.
- Probability is finite positive float64.
- Scores are ordered lexicographically by `(home_goals, away_goals)` using the
  explicit contiguous ordinal.
- A deferred constraint requires total mass of one within `1e-12`.

### `simulation.distribution_provenance`

- Primary key: a content-derived UUID over the complete provenance record.
- Required foreign key: scoreline distribution.
- Stores producer kind, producer identity and version, exact input or artifact
  checksum, runtime/numerical contract and approval context.
- One distribution may have multiple independent provenance attestations
  without changing its content identity.
- No current production producer is assumed. Existing test and explicit caller
  inputs use an `explicit_input` origin.
- A model artifact may be referenced only if its separate score-model and
  prediction contracts declare scoreline capability. The current CatBoost
  artifact fails that constraint and therefore cannot produce a distribution.

### `simulation.simulation_input`

- Primary key: `input_sha256`, calculated from the exact canonical input bytes;
  no generated surrogate ID.
- Required foreign keys: competition-season and exact input `stored_object`.
- Stores simulation schema version.
- `simulation.simulation_input_team(input_sha256, ordinal)` preserves exactly
  20 unique team UUIDs in the established canonical UUID order.
- `simulation.simulation_input_completed_fixture(input_sha256, ordinal)` owns
  the immutable completed ledger and score.
- `simulation.simulation_input_batch(input_sha256, batch_ordinal)` stores the
  date-only or exact simultaneous boundary.
- `simulation.simulation_input_remaining_fixture` preserves fixture order,
  kickoff, precision, distribution ID, selected distribution-provenance ID and
  batch membership.
- Completed and remaining fixture IDs must be unique and disjoint; every team
  must be a season member; every remaining fixture must have a provenance-bound
  distribution matching its fixture and teams.

## Simulation runs and summaries

### `simulation.simulation_run`

- Primary key: existing deterministic `simulation_id uuid`.
- Required foreign key: simulation input checksum.
- Stores schema version, algorithm version, unsigned 64-bit seed and run count.
- Version 1 requires algorithm version 1 and exactly 10,000 runs.
- Unique constraint:
  `(input_sha256, simulation_seed, algorithm_version, simulation_count)`.
- The UUID is recomputed from the complete canonical input, seed, algorithm
  version and fixed count before insertion.

### `simulation.result_component`

- Primary key: `(simulation_id, role)`.
- Required foreign key to an exact `stored_object` with
  `canonicalization_profile = numpy_array_v1`.
- Roles are `points`, `goals_for`, `goals_against`, `sampled_home_goals`,
  `sampled_away_goals` and `position_mass`.
- Role-specific checks require:
  `int64` for the three table matrices, `int16` for sampled goals and `float64`
  for position mass.
- Explicit shape and axis-order fields preserve `(run, team)`, `(run, fixture)`
  and `(run, team, position)` semantics. Values are immutable.

This table defines the future persistence shape but does not authorize Step 5.1
to serialize or store simulation matrices.

### `simulation.simulation_summary`

- Primary key: existing deterministic `summary_id uuid`.
- Required one-to-one foreign key to simulation run and exact canonical summary
  bytes when serialization is later introduced.
- Stores schema version, algorithm version, count and season; version 1 repeats
  the fixed 10,000-run constraint.

### `simulation.team_summary`

- Primary key: `(summary_id, team_id)`.
- Unique `team_ordinal` preserves canonical team order.
- Stores finite float64 expected points, goals for, goals against and goal
  difference, plus champion, top-four, top-six and relegation probabilities.
- Expected goal difference must equal expected goals for minus expected goals
  against within `1e-12`.

### `simulation.position_probability`

- Primary key: `(summary_id, team_id, position)`.
- Position is between 1 and 20; probability is finite and within `[0,1]`.
- Every summary must contain exactly 20 teams and 400 position rows.
- Deferred constraints require each team's mass and each position's mass to
  equal one within `1e-12`.
- Team threshold probabilities must equal the appropriate position sums.
- League-wide champion, top-four, top-six and relegation mass must equal one,
  four, six and three respectively.
- Fractional mass over unresolved playoff positions is valid; an invented
  winner or identifier-based sporting tiebreak is not.

The summary UUID is recomputed from the simulation ID, season, algorithm/count
contract and exact ordered team summaries.

## Ownership, immutability and deletion

All entities described here are immutable after successful insertion. A later
migration must add fail-closed guards that reject `UPDATE` and `DELETE` for
exact content, source captures, reference revisions, canonical datasets and
fixture revisions, feature/training/evaluation artifacts, freezes, models,
artifact manifests and components, registry entries and events, distributions,
simulation inputs, runs, result components and summaries.

Logical ownership determines validation boundaries:

- a dataset owns its ordered record projections;
- a feature row owns its values and optional label;
- a training example owns its separate target;
- an artifact owns ordered components;
- a registry entry owns its event sequence;
- a distribution owns its score masses but not its independent provenance;
- a simulation input owns ordered teams, completed fixtures and remaining
  fixture selections; and
- a summary owns team and position aggregates.

Ownership does not authorize cascading deletion. Every provenance foreign key
uses `ON UPDATE RESTRICT ON DELETE RESTRICT`. Archival, rejection, retirement or
supersession is represented by metadata or append-only events, never physical
deletion. Administrative removal, if ever required, needs a separately reviewed
break-glass policy outside ordinary repositories.

## Fail-closed validation layers

Validation is cumulative; normalized rows never excuse missing or modified
canonical bytes.

1. **Typed import validation:** Load the existing strict Pydantic contract,
   verify raw manifests first, require canonical bytes and recompute existing
   UUID/checksum identities before opening a transaction.
2. **Immediate database constraints:** Enforce types, enum values, ranges,
   exact role/version pins, local row consistency, primary keys, foreign keys
   and uniqueness.
3. **Identity and content triggers:** Immutable PostgreSQL functions using its
   digest and UUIDv5 capabilities recompute applicable checksums and existing
   deterministic IDs; supplied values must match. The migration must test these
   functions against identifiers already present in the repository.
4. **Deferred constraint triggers:** Enforce gap-free ordering, dataset counts,
   season shape, predictor completeness, checksum-linked registry history,
   chronology, probability mass and aggregate conservation at transaction end.
5. **Immutable-row guards:** Reject updates or deletes after insert.
6. **Repository verification:** After insert, reload by identity and compare
   exact bytes and all normalized relationships before commit or publication.

Stable application failure categories map to named database constraints:

| Failure category | Representative database failure |
| --- | --- |
| `identity_mismatch` | Supplied UUID/content key does not equal recomputed identity |
| `checksum_mismatch` | Stored bytes, declared size or SHA-256 disagree |
| `non_canonical_bytes` | Bytes violate their declared canonicalization profile |
| `provenance_mismatch` | Dataset, fixture, source or manifest foreign keys disagree |
| `chronology_violation` | Cutoff or simultaneous-batch boundary is invalid |
| `predictor_schema_incompatible` | Missing, unknown, duplicated or reordered predictor |
| `outcome_order_incompatible` | Outcome contract differs from home/draw/away order |
| `runtime_incompatible` | Python/library/dtype/runtime pin differs |
| `numerical_contract_mismatch` | Non-finite value, wrong dtype or wrong matrix shape |
| `invalid_probability_mass` | Prediction, scoreline or position mass is incomplete |
| `registry_transition_invalid` | Event sequence, checksum link or state edge is invalid |
| `final_test_evidence_required` | Activation is attempted under registry schema v1 |
| `immutable_record_violation` | An update or deletion targets immutable history |

Unknown schema versions, discriminator values, fields, artifact roles,
compatibility versions and lifecycle transitions fail closed. A repository may
not downgrade a constraint failure to a warning or silently coerce a value.

## Migration allocation after Step 5.1

This ER model controls later work in the roadmap:

- **Step 5.2:** settings and local/test PostgreSQL connections only;
- **Step 5.3:** Alembic initialization only;
- **Step 5.4:** checked domains, exact-content lineage, identity, reference,
  season and fixture structures;
- **Step 5.5:** predictor schemas, feature/Elo entities and semantic model plus
  artifact structures;
- **Step 5.6:** training/test-boundary, prediction and evaluation structures;
- **Step 5.7:** scoreline-distribution, simulation, raw-ingestion and future
  provider-cache structures;
- **Step 5.8:** typed repositories and exact-byte import behavior; and
- **Step 5.9:** PostgreSQL transaction, immutability, constraint and integration
  tests.

No later migration may replace existing UUIDv5 or content-derived identities
with generated keys, reconstruct canonical bytes from `jsonb`, weaken the
untouched-test boundary, infer scorelines from three-way probabilities or make
development acceptance equivalent to activation.
