# Model Artifacts and Registry

## Scope

Steps 4.1 through 4.3 define the deterministic model-artifact boundary,
serialize and reload the selected development model and record it in an
append-only local registry. They do not evaluate the untouched test season,
activate a production model, simulate a season or add persistence, APIs or
deployment behavior.

Every model build begins by running the existing assessment and training
materializers. Raw files are therefore verified against
`data/manifests/football-data.json` before any upstream checksum is trusted.
Only the 3,800 examples from 2015–16 through 2024–25 are fitted. The target-free
2025–26 freeze is carried into provenance unchanged.

## Artifact layout

Layout version 1 is rooted below ignored `artifacts/`:

```text
artifacts/models/v1/<model-id>/<artifact-id>/
├── manifest.json
└── components/
    ├── preprocessor.json
    └── classifier.json
```

Paths in the manifest are canonical POSIX relative paths. Absolute paths,
backslashes, traversal segments, unknown files and reordered components are
rejected. The required component order is preprocessor followed by classifier.

The preprocessor is a stateless contract, not a fitted transformer. It requires
the complete `epl-pre-match` version 2 predictor order, converts booleans to
zero or one, casts integers and floats to NumPy float64 and maps nulls to NaN.
CatBoost handles those NaNs with its pinned `Min` policy. There are no learned
imputation or scaling values.

The classifier is the selected `catboost-depth6-regularized` model: 200 trees,
depth 6, learning rate 0.05 and L2 leaf regularization 10. It produces only
three full-time outcome probabilities in the fixed order `home_win`, `draw`,
`away_win`. Calibration is the selected parameter-free identity transform.
No score model is included and the artifact makes no scoreline-generation
claim. Poisson and Dixon–Coles remain evaluated development models only.

## Stable identities

All identities are UUIDv5 values derived from a SHA-256 of compact, key-sorted
identity JSON:

- the model ID binds the selected policy, predictor and outcome contracts,
  development training bytes, assessment and untouched-test freeze;
- each component ID binds its model, role, path, format, byte count and exact
  SHA-256;
- the artifact ID binds the ordered component IDs and layout version; and
- the manifest ID binds the complete manifest body except the manifest ID
  itself.

The checksum of `manifest.json` is calculated externally because a manifest
cannot contain the checksum of its own final bytes without a cycle.

## Canonical bytes and checksums

Persisted JSON uses UTF-8 without a byte-order mark, Unicode characters are not
ASCII-escaped, object keys are sorted, indentation is two spaces, non-finite
numbers are prohibited and exactly one trailing line feed is present. Identity
JSON is compact and key-sorted. SHA-256 digests are lowercase 64-character
hexadecimal values over the exact bytes.

CatBoost's default binary and JSON exports contain a random model GUID and a
wall-clock training-finish value. The serializer uses CatBoost's supported JSON
model format and replaces only those two non-predictive values with the stable
model ID and `1970-01-01T00:00:00Z` before canonical serialization. Loading
requires canonical bytes, exact component sizes and checksums, the correct
three-class order, 200 trees and 175 features. A build also compares all 3,800
pre- and post-serialization development predictions and allows at most four
float64 machine epsilons of raw numerical round-trip difference.

## Runtime and compatibility

Version 1 requires exact compatibility with 64-bit CPython 3.14.7, CatBoost
1.2.10, NumPy 2.5.3 float64, Pydantic 2.13.5 and tzdata 2026.3. It also requires
manifest schema version 1, layout version 1, the complete 175-name predictor
schema and checksum and the fixed three-outcome order. Unknown fields, versions,
components or predictors fail closed.

## Provenance

The artifact manifest embeds the complete training manifest. That manifest
enumerates every feature dataset, feature-manifest checksum, canonical fixture
checksum, recursive historical-context checksum, raw source identity, capture
time and checksum and the historical, team and season registry checksums.

It also records the base evaluation, CatBoost tuning and advanced-evaluation
manifest and prediction checksums; embeds the complete development assessment;
and embeds the target-free untouched-test freeze. Validation cross-checks every
checksum and requires the assessment to select CatBoost depth 6 with identity
calibration. No training rows, evaluation prediction rows, test outcomes or
test scores are copied into the model manifest.

Build or reproduce the artifact with:

```powershell
plp-build-model-artifact `
  --manifest data/manifests/football-data.json `
  --teams data/reference/teams.json `
  --seasons data/reference/seasons.json `
  --data-root data `
  --artifact-root artifacts
```

## Append-only registry

Registry schema version 1 stores an immutable entry and checksum-linked events:

```text
artifacts/registry/v1/entries/<entry-id>/
├── entry.json
└── events/
    ├── 000001-<event-id>.json
    └── 000002-<event-id>.json
```

Registration fully loads and verifies the artifact before creating the
`candidate` event. A candidate may become `development_accepted` only when its
embedded, checksum-verified assessment contains the frozen accepted CatBoost
policy. Candidate or development-accepted entries may be rejected with an
immutable reason. Rejected entries are terminal.

`active` and `retired` are reserved states, but version 1 deliberately cannot
write an activation event: active promotion fails with
`final_test_evidence_required` until a future typed, explicitly authorized
one-time final-test evaluation contract exists. Development acceptance is not
production activation.

Register and optionally record development acceptance with:

```powershell
plp-register-model-artifact `
  --artifact-manifest <artifact-manifest-path> `
  --artifact-root artifacts `
  --registry-root artifacts/registry `
  --accept-development
```

Failures use stable categories for invalid manifests, identities and paths;
missing, modified or non-canonical components; runtime, predictor or outcome
incompatibility; provenance drift; invalid registry transitions; and missing
final-test evidence.

## Active-model read boundary

Step 7.1 adds a stateless, read-only resolver over this existing layout. It
enumerates every canonical registry entry in deterministic UUID order and calls
the complete entry/event-history validator before considering current state.
No state column, marker file, symlink or mutable active pointer is consulted or
created. `development_accepted` remains non-active.

The resolver requires exactly one history whose final event derives `active`.
Zero active histories return the typed `no_active_model` failure; multiple
active histories return `ambiguous_active_models` before any artifact is loaded.
Malformed registry history is never skipped merely because another entry looks
usable.

For one active entry, loading verifies this chain in order:

1. canonical registry layout, entry bytes and complete event/checksum history;
2. manifest containment below the explicit artifact root and exact registry
   manifest SHA-256;
3. registry entry, semantic model, artifact and manifest identities;
4. canonical manifest bytes and complete embedded training, assessment,
   evaluation and target-free freeze provenance;
5. exact CPython, CatBoost, NumPy, Pydantic, tzdata, CPU/thread and float64
   compatibility;
6. required preprocessor/classifier paths, byte counts, SHA-256 values and
   canonical bytes;
7. stateless preprocessor and exact 175-name schema-version-2 predictor order;
8. CatBoost multiclass depth-6 structure, identity calibration, explicit absent
   score model, no scoreline capability and outcome order `home_win`, `draw`,
   `away_win`.

The returned value contains the immutable verified registry head and the loaded
artifact. Loading does not call the classifier's prediction method. Stable
active-boundary failures distinguish no active model, ambiguity, malformed
history, missing artifacts, checksum drift, schema/runtime incompatibility,
unsupported components, provenance disagreement and noncanonical bytes.

Synthetic tests inject a typed active registry snapshot and use real temporary
artifact bytes to verify the successful path. They do not append an active
event. The actual registry still ends at `development_accepted` and therefore
correctly returns `no_active_model`.

Steps 7.2 through 7.4 consume this boundary without weakening it. Operational
prediction accepts only the returned `LoadedActiveModel`, rechecks the exact
predictor names and records the registry head event checksum plus model,
artifact and manifest identities with each immutable prediction. Identity
calibration means the three CatBoost probabilities are stored unchanged in
`home_win`, `draw`, `away_win` order. A development-accepted artifact cannot
enter this path and no classifier probability is interpreted as a scoreline.

## PostgreSQL persistence projection

The Step 5.1
[entity-relationship model](../architecture/postgresql-entity-relationship-model.md)
keeps semantic model, classifier specification, stateless preprocessing,
identity calibration, explicit absent-score-model metadata, prediction contract
and runtime requirements in separate one-to-one relations. The semantic
`model_id`, physical `artifact_id`, `manifest_id`, component UUIDs and registry
`entry_id` and event UUIDs remain their existing content-derived identities;
none receives a database-generated replacement.

Artifact manifests and each component retain their exact immutable bytes,
external SHA-256 and byte count. Component order, role, relative path and format
are also normalized with explicit ordinals so relational loading can verify the
same preprocessor-then-classifier contract without reconstructing bytes from
database JSON.

Registry entries have no mutable state or active pointer. State is derived from
the latest event in a gap-free, checksum-linked, append-only sequence. Database
constraints preserve `candidate`, `development_accepted` and terminal
`rejected` behavior and reject version-1 activation with
`final_test_evidence_required`. The currently registered artifact therefore
remains development-accepted and not active.

Scoreline distributions live in the separate simulation schema with their own
producer provenance. The current classifier's `produces_scorelines = false`
contract prevents it from being referenced as a distribution producer.
