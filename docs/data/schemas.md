# Data Schemas

The data pipeline uses five deliberately separate representations.

## Raw source file

The downloaded CSV is immutable and retains all provider columns. Integrity is
established by the tracked manifest before parsing.

## Football-Data source model

`FootballDataMatch` parses the provider's abbreviated columns into typed fields.
It validates dates, scores, result codes, non-negative match statistics, and row
identity. Odds and other columns that are not yet modeled remain available in
`additional_fields`; retaining a field does not make it an eligible ML feature.

Dates and times remain source-local at this boundary. Football-Data's English
match time is interpreted in the `Europe/London` timezone only when a canonical
fixture is created.

## Canonical fixture model

`Fixture` is provider-independent. It uses:

- stable canonical team UUIDs;
- a deterministic fixture UUID;
- a canonical competition and season identifier;
- timezone-aware UTC kickoff timestamps with explicit kickoff precision;
- explicit status, score, outcome, statistics, and source references.

The canonical model rejects inconsistent scores, outcomes, teams, kickoff
timestamps, and fixture states.

## Point-in-time feature-row model

`PointInTimeFeatureRow` schema version 1 is the provider-independent boundary
between canonical fixtures and point-in-time feature processing. It is an
immutable, strictly validated envelope with these sections:

- `id`: deterministic UUIDv5 identity for the fixture, feature cutoff,
  predictor schema, feature-row schema, and canonical input dataset;
- `fixture_id`, `competition_id`, `season_id`, `home_team_id`, and
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
  fixture checksum, verified raw artifact identity and checksum, source capture
  time, and team and season registry schema versions.

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
representable without using sentinel target values, and downstream training
code can select labels without exposing them as predictors.

All contract timestamps are timezone-aware UTC. For an exact kickoff, the
feature cutoff may equal but cannot follow kickoff. For `date_only` fixtures,
the cutoff must precede midnight at the start of the source-local fixture date
in `Europe/London`, converted to UTC. This deliberately conservative boundary
prevents the noon anchor from implying an observed within-day order and remains
correct across daylight saving transitions. Chronological processing treats
every fixture on a local date containing a date-only record as one simultaneous
batch, calculates all rows from pre-batch state, and updates state only after
the full batch.

The feature-row contract and calculator do not read raw provider files. Feature
materialization must start from canonical datasets produced only after raw
manifest verification and must carry their recorded checksums into provenance.

The predictor schema and calculation semantics are documented in
[Point-in-Time Feature Processing](../features/point-in-time.md).

## Processed feature dataset

Each completed season materializes as deterministic JSON Lines at
`data/processed/features/epl/<season>/features.jsonl` with an adjacent
`dataset-manifest.json`. The manifest pins the feature dataset, row, predictor,
and chronology versions; the ordered 134-name predictor schema and checksum;
the feature-file count and checksum; processing-window semantics; canonical
fixture lineage; registry versions; and the verified raw artifact lineage.

The materializer invokes checksum-verifying canonical materialization before
reading canonical inputs, validates the canonical file against its own manifest,
and publishes generated outputs atomically. Equivalent inputs produce identical
bytes and checksums. Processed feature files remain ignored generated artifacts.

## Reproducible training dataset

`TrainingExample` schema version 1 is the model-ready projection of a verified
feature row. It retains fixture, competition, season, and canonical team
identity; kickoff, kickoff precision, and feature cutoff; the complete versioned
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
- the historical manifest, team registry, and season registry checksums; and
- every source feature dataset and manifest checksum plus its canonical and raw
  lineage.

The loader rejects modified bytes, wrong row counts, predictor-schema drift,
unknown or cross-season feature references, and incomplete season coverage.
The artifact contains all 4,180 completed fixtures; temporal splitting and model
fitting remain later work.

## Team identity

`data/reference/teams.json` contains 34 stable team records covering every club
in the historical window, with explicit aliases per source. Resolution
normalizes Unicode, capitalization, and redundant whitespace, but deliberately
avoids fuzzy matching. A new or changed provider name must be reviewed and added
to the registry rather than guessed.

## Season membership and transitions

`data/reference/seasons.json` records the 20 canonical teams participating in
each season from 2015–16 through 2025–26 and marks the three promoted clubs with
their previous competition. This keeps promotion status point-in-time correct
instead of inferring it later from a final league table.

## Canonical interim dataset

The materializer parses and canonicalizes a manifest entry, runs competition-wide
quality checks, and writes deterministically ordered JSON Lines to
`data/interim/canonical/epl/<season>/fixtures.jsonl`. A generated companion
manifest records:

- canonical dataset schema version
- source file ID, capture timestamp, and checksum
- team and season registry schema versions
- fixture count and output checksum

The interim dataset is reproducible and ignored by Git. Re-running the pipeline
with unchanged inputs produces the same bytes and returns `already_current`.

## Missing and postponed data policy

- Date, teams, full-time score, and result are mandatory for completed historical
  rows; malformed values fail parsing.
- Half-time values, referee, and match statistics are nullable so older schemas
  can be represented without fabricated values.
- When only a date is available, canonicalization sets `kickoff_precision` to
  `date_only` and anchors the UTC timestamp at noon Europe/London. Later
  point-in-time processing must treat all date-only matches on the same date as
  a batch, not infer an ordering from the anchor.
- Unavailable optional statistics generate quality warnings, not invented zeros.
- A postponed fixture retains its stable identity based on competition, season,
  home team, and away team. Its status and kickoff can be revised when a provider
  supplies the rescheduled time.
- Completed-season datasets cannot contain scheduled, postponed, cancelled, or
  in-progress fixtures.

## Competition-wide quality rules

For a completed 20-team Premier League season, validation requires 380 fixtures,
unique fixture IDs, unique ordered home/away pairings, registered teams, in-season
kickoff dates, final statuses, and 19 home plus 19 away fixtures per club.
