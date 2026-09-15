# Current Players, Squads and Recorded-Response Contracts

## Step 6.8 scope

Players and squads are optional provider capabilities. Their absence cannot
block the required team, fixture, status and result path. Provider player and
squad identifiers are source-scoped opaque values and never become canonical
player, team, fixture, competition or season identities.

`PlayerRegistry` resolves a provider player only through a reviewed exact
external ID or normalized exact alias. If ID and name evidence disagree, either
maps to multiple players or is unknown, transformation fails. Fuzzy and
similarity matching are prohibited. Canonical player UUIDs are supplied by the
reviewed registry; provider metadata cannot derive or replace them.

Player responses may retain provider name, birth date, nationality and
position. The name and identifiers are identity controls. The descriptive
fields require a later reviewed predictor-schema decision and are not approved
predictors. Exact unmodeled fields remain only in cached response bytes.

## Membership and chronology

Each squad is scoped to one canonical competition, season, team and explicit
source-local `as_of_date`. A membership records both its effective employment
window and its registration/eligibility window. The registration must be active
on the snapshot date and cannot precede employment or outlive an explicit
employment end. Loan memberships require an exact, distinct reviewed parent
team; non-loans prohibit one. Shirt number is optional retained context and is
predictor-prohibited.

Transformation requires all provider teams and players to have already passed
exact reviewed resolution. A snapshot contains every one of the season's 20
reviewed teams exactly once, has one source/scope/date and prohibits a player
from having two simultaneously active registrations. Teams and members use
canonical UUID ordering. Squad UUIDs are provider-independent UUIDv5 values of
competition, season and canonical team.

Squad membership is authoritative state only after the response retrieval
knowledge boundary. It cannot affect the same or an earlier fixture and does
not alter the existing 175-field predictor schema.

## Immutable persistence

Revision `f0006_step_6_8` adds canonical players, exact player and squad source
references, cache-provenanced player observations, canonical season/team squads
and complete squad snapshots. Snapshot identity is UUIDv5 over canonical
identity JSON whose SHA-256 binds scope, date, ordered teams, memberships and
all cache provenance.

Deferred PostgreSQL validation repeats the application boundary. It checks the
20 reviewed teams, canonical ordering, nonempty squads, exact cached metadata
source and retrieval time, player observations known by the snapshot cutoff,
active in-season registration windows and valid loan parents. Every table is
immutable and every provenance foreign key is restrictive. Writes still pass
the historical raw-data manifest gate before a transaction starts.

## Step 6.9 recorded-response corpus

The repository includes a small synthetic, credential-free response recording
for each of the seven provider-neutral capabilities. A strict manifest binds
each relative path to capability, source, canonical request-identity SHA-256,
exact response SHA-256, retrieval/provider timestamps, compatibility versions,
pagination, quota and HTTP/media metadata.

Replay is offline. It rejects absolute, parent-traversal, missing and escaped
paths; incomplete or reordered capability coverage; source, capability,
request-identity or compatibility disagreement; corrupt bytes; non-UTC or
future provider timestamps; and non-success status. It returns the same typed
`ProviderResponseCapture` used by cache and transformation boundaries without
changing response bytes. The synthetic envelopes do not select a provider or
pretend to be vendor parsers.

## Explicit exclusions

Steps 6.8 and 6.9 do not add a production provider, credentials, live network
traffic, a scheduler, production corpus or artifact import, new predictors,
final-test access, active model promotion, predictions, scoreline inference,
simulation changes, APIs, deployment, frontend or CI/CD configuration.
