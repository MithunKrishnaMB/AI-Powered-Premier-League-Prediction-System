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
