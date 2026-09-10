# Historical Data Schemas

The historical pipeline uses three deliberately separate representations.

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
- timezone-aware UTC kickoff timestamps;
- explicit status, score, outcome, statistics, and source references.

The canonical model rejects inconsistent scores, outcomes, teams, kickoff
timestamps, and fixture states.

## Team identity

`data/reference/teams.json` contains stable team records and explicit aliases per
source. Resolution normalizes Unicode, capitalization, and redundant whitespace,
but deliberately avoids fuzzy matching. A new or changed provider name must be
reviewed and added to the registry rather than guessed.

## Season membership and transitions

`data/reference/seasons.json` records the 20 canonical teams participating in a
season and marks the three promoted clubs with their previous competition. This
keeps promotion status point-in-time correct instead of inferring it later from a
final league table. The 2025–26 promoted clubs are Burnley, Leeds United, and
Sunderland.

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
- Kickoff time, half-time values, referee, and match statistics are nullable so
  older schemas can be represented without fabricated values.
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
