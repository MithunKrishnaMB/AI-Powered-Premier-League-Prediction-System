# Point-in-Time Feature Processing

## Processing boundary

`build_point_in_time_feature_rows` consumes validated canonical `Fixture`
objects, one reviewed `PremierLeagueSeason`, explicit opening priors, initial Elo
state and provenance copied from verified manifests. It produces immutable
`PointInTimeFeatureRow` objects in memory and applies updates only after each
chronological batch.

The builder rejects fixtures whose competition, season, membership, final
status or source reference disagrees with the supplied season and provenance.
It does not parse raw provider files. The feature materializer retains the
existing manifest-verification and canonicalization path.

## Deterministic feature datasets

`plp-materialize-features` materializes one season or the full manifest window.
Because opening priors and Elo transitions depend on preceding seasons, a
single-season request verifies and processes every manifest entry from the start
of the historical window through the requested season. Each entry runs through
the existing canonical materializer, which verifies the checksum-pinned raw file
before parsing. The feature materializer then re-reads canonical JSON Lines and
their manifest, verifies checksum, count, source capture, competition, season,
and registry versions and only then advances feature state.

Rows are sorted by feature cutoff, kickoff and deterministic feature-row UUID,
then serialized as compact, key-sorted UTF-8 JSON Lines at
`data/processed/features/epl/<season>/features.jsonl`. The adjacent
`dataset-manifest.json` records:

- feature-dataset, feature-row, predictor and chronology schema versions;
- the complete ordered list of 175 predictor names and its SHA-256;
- feature-row count and feature-file SHA-256;
- the five-match form window, opening-prior policy and constants, Elo policy and
  constants, date-only timezone and within-season state-reset policy;
- the recursive historical-context checksum and immediate prior canonical
  source when one exists;
- canonical dataset identity, schema version, fixture count, checksum and
  registry versions; and
- raw source, artifact, capture time and checksum.

Both the manifest and its rows are loaded through typed validators before they
can become training inputs. The loader rechecks the feature-file checksum and
count, the exact ordered predictor names, competition and season identity and
the canonical/raw lineage carried by every row.

Generated files are ignored by Git. Publication uses atomic file replacement,
stale generated outputs are safely replaced and a byte-identical rerun returns
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

## Predictor schema version 2

Predictors use schema ID `epl-pre-match` and version `2`. State resets at the
start of each Premier League season, while separately represented opening priors
and Elo ratings carry only the approved cross-season information. No
lower-division results are inferred; promoted status and prior source flags
explicitly represent that boundary.

For both the home and away team, the schema contains:

- season-to-date prior matches, wins, draws, losses, points, points per match,
  and win/draw/loss rates;
- the same result rates and points over the five most recent prior matches;
- season-to-date and five-match goals-for and goals-against averages;
- season-to-date and five-match averages for shots, shots on target, fouls,
  yellow cards and red cards, both for and against;
- an observation count beside every optional-statistic average;
- calendar-day rest since the team's prior match;
- prior-match counts in the preceding 7 and 14 calendar days; and
- venue-specific prior match count, points per match and win rate: home history
  for the home team and away history for the away team.

Fixture-level context contains the two promoted-team flags, the count of prior
season fixtures and season progress. Season progress divides the prior-fixture
count by the competition schedule size derived from reviewed season membership
(380 for a 20-team double round robin).

Rates and averages are null when they have no prior denominator. Optional match
statistics ignore missing observations and publish the observed denominator;
missing values are never converted to zero. Goals and results are mandatory for
the completed historical fixtures accepted by the builder.

## Season-opening priors

Opening-prior schema version 1 is fixed before a season begins:

- a continuing club uses its own immediately preceding Premier League season;
- a promoted club uses the preceding Premier League aggregate because no
  Championship results are present in the verified input window; and
- every club in the first tracked season uses a fixed neutral baseline of equal
  win/draw/loss rates, 4/3 points per match and 1.5 goals for and against.

Prior result and goal values have a five-match pseudo-weight. Separate blended
predictors combine those values with the current season's already-observed
results. Factual match and observation counts remain factual; pseudo-matches are
never inserted into rolling state. Three mutually exclusive Boolean source
flags and the historical reference-match count make fallback behavior visible
to downstream models.

## Point-in-time Elo

Elo schema version 1 uses these frozen parameters:

- initial rating: 1500;
- home advantage: 65 rating points;
- K-factor: 20;
- rating scale: 400; and
- offseason retention: 75% of a continuing club's deviation from 1500.

Promoted clubs initialize at 1500. The first tracked season initializes every
club at 1500. Each row exposes the two pre-match ratings, complementary expected
scores, raw and home-adjusted rating differences and the home-advantage
constant. For a simultaneous batch, every prediction reads the same rating
snapshot. Match deltas are accumulated from that snapshot and committed only
after every fixture in the batch, preserving both date-only uncertainty and
zero-sum within-season updates.

## Leakage controls

- Only observations committed after an earlier batch may enter predictors.
- The current fixture's score, outcome and statistics never enter its own
  predictor state.
- Training outcome and score remain in the separate `training_label` object.
- Provider columns and bookmaker odds have no ingestion path into the approved
  predictor builder.
- Team identities come only from canonical UUIDs and reviewed season
  membership; feature processing performs no alias or fuzzy matching.
- Row IDs include fixture identity, cutoff, predictor schema and canonical
  dataset checksum plus a recursive historical-context checksum, so changed
  prior-season lineage cannot silently retain the same identity.

Focused boundary tests perturb current and future targets, mix exact and
date-only chronology, exercise British daylight saving boundaries, preserve
missing optional values, reverse input order, corrupt checksums and lineage and
verify opening-prior sources, offseason Elo transitions, shared pre-batch Elo
snapshots, atomic publication and idempotent rebuilding.
