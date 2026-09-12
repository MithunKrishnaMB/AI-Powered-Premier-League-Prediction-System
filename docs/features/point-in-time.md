# Point-in-Time Feature Processing

## Processing boundary

`build_point_in_time_feature_rows` consumes validated canonical `Fixture`
objects, one reviewed `PremierLeagueSeason`, and provenance copied from the
canonical dataset manifest and its verified source manifest. It produces
immutable `PointInTimeFeatureRow` objects in memory.

The builder rejects fixtures whose competition, season, membership, final
status, or source reference disagrees with the supplied season and provenance.
It does not parse raw provider files. The feature materializer retains the
existing manifest-verification and canonicalization path.

## Deterministic feature datasets

`plp-materialize-features` materializes one season or the full manifest window.
It first runs the existing canonical materialization entry point, which verifies
the checksum-pinned raw file before parsing. It then re-reads the canonical JSON
Lines and companion manifest, verifies their checksum, count, source capture,
competition, season, and registry versions, and only then builds features.

Rows are sorted by feature cutoff, kickoff, and deterministic feature-row UUID,
then serialized as compact, key-sorted UTF-8 JSON Lines at
`data/processed/features/epl/<season>/features.jsonl`. The adjacent
`dataset-manifest.json` records:

- feature-dataset, feature-row, predictor, and chronology schema versions;
- the complete ordered list of 134 predictor names and its SHA-256;
- feature-row count and feature-file SHA-256;
- the five-match window, date-only timezone, and season-reset policy;
- canonical dataset identity, schema version, fixture count, checksum, and
  registry versions; and
- raw source, artifact, capture time, and checksum.

Both the manifest and its rows are loaded through typed validators before they
can become training inputs. The loader rechecks the feature-file checksum and
count, the exact ordered predictor names, competition and season identity, and
the canonical/raw lineage carried by every row.

Generated files are ignored by Git. Publication uses atomic file replacement,
stale generated outputs are safely replaced, and a byte-identical rerun returns
`already_current`.

## Chronology and simultaneous batches

Processing is deterministic across input orders:

1. Fixtures are partitioned by their Premier League calendar date in
   `Europe/London`.
2. If a date contains any `date_only` fixture, every fixture on that date forms
   one simultaneous batch. This conservative rule also absorbs exact-time
   fixtures on the date because they cannot safely order an unknown kickoff.
3. A date containing only exact kickoffs is partitioned by identical UTC
   kickoff timestamp.
4. Dates and exact timestamps are chronological; fixture UUID orders rows only
   within a simultaneous batch.
5. Every row in a batch is calculated from the same pre-batch team state.
6. Results and match statistics update team state only after all rows in the
   batch have been created.

The feature cutoff for an exact batch is its kickoff timestamp. The cutoff for
a date-only batch is one microsecond before midnight begins its source-local
fixture date, converted to UTC. This remains correct across British daylight
saving transitions. The cutoff is an information boundary, not an assertion
that every source value was published precisely at that instant.

## Predictor schema version 1

Predictors use schema ID `epl-pre-match` and version `1`. State resets at the
start of each Premier League season. No prior-season or lower-division matches
are silently inferred; promoted status explicitly represents that context.

For both the home and away team, the schema contains:

- season-to-date prior matches, wins, draws, losses, points, points per match,
  and win/draw/loss rates;
- the same result rates and points over the five most recent prior matches;
- season-to-date and five-match goals-for and goals-against averages;
- season-to-date and five-match averages for shots, shots on target, fouls,
  yellow cards, and red cards, both for and against;
- an observation count beside every optional-statistic average;
- calendar-day rest since the team's prior match;
- prior-match counts in the preceding 7 and 14 calendar days; and
- venue-specific prior match count, points per match, and win rate: home history
  for the home team and away history for the away team.

Fixture-level context contains the two promoted-team flags, the count of prior
season fixtures, and season progress. Season progress divides the prior-fixture
count by the competition schedule size derived from reviewed season membership
(380 for a 20-team double round robin).

Rates and averages are null when they have no prior denominator. Optional match
statistics ignore missing observations and publish the observed denominator;
missing values are never converted to zero. Goals and results are mandatory for
the completed historical fixtures accepted by the builder.

## Leakage controls

- Only observations committed after an earlier batch may enter predictors.
- The current fixture's score, outcome, and statistics never enter its own
  predictor state.
- Training outcome and score remain in the separate `training_label` object.
- Provider columns and bookmaker odds have no ingestion path into the approved
  predictor builder.
- Team identities come only from canonical UUIDs and reviewed season
  membership; feature processing performs no alias or fuzzy matching.
- Row IDs include fixture identity, cutoff, predictor schema, and canonical
  dataset checksum, so changed lineage cannot silently retain the same identity.

Focused boundary tests perturb current and future targets, mix exact and
date-only chronology, exercise British daylight saving boundaries, preserve
missing optional values, reverse input order, corrupt checksums and lineage, and
verify atomic and idempotent publication.
