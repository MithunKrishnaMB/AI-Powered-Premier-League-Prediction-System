# Current-Provider Capability and Domain Contracts

## Scope

Step 6.1 defines the provider-neutral boundary for current-season teams,
fixtures, fixture status, completed results and standings. It introduces no
provider selection, provider-specific transformation, authentication, network
client, retry loop, quota enforcement, cache write, synchronization or database
migration.

Every executable contract is immutable and rejects unknown fields. Provider
identifiers remain opaque external values; canonical competition and season
identities remain platform strings and canonical team and fixture identities
remain platform UUIDs.

## Capability declaration

`ProviderCapabilityManifest` contains exactly one declaration, in this order,
for each operation:

1. `current_season_teams`
2. `current_season_fixtures`
3. `fixture_status`
4. `completed_results`
5. `standings`

Availability and platform requirement are separate:

- availability is `supported`, `unsupported` or `temporarily_unavailable`;
- teams, fixtures, fixture status and completed results are `required`; and
- standings are `optional` because the platform can reconstruct a table from
  reconciled completed results.

Unsupported and temporarily unavailable capabilities require a reason.
Unsupported capabilities cannot claim pagination or retry timing. Temporary
unavailability may identify when the Step 6.3 policy can retry; the capability
contract itself performs no retry.

## Provider and canonical identities

The four provider identifier types are deliberately distinct:

- `ProviderCompetitionIdentifier`
- `ProviderSeasonIdentifier`
- `ProviderTeamIdentifier`
- `ProviderFixtureIdentifier`

Each value is identified by `(source_id, external_id)`. It cannot substitute
for a canonical identity or participate directly in canonical fixture UUID
generation.

`CurrentSeasonScope` pairs an expected canonical competition and season with
explicit provider competition and season identifiers from one source. The
current season is never inferred from the wall clock.

Team resolution must use an exact reviewed source alias or reviewed external
ID. Existing harmless Unicode, case and whitespace normalization remains
permitted. Similarity, fuzzy matching, guessed aliases and provider-ID-to-UUID
coercion are prohibited. Unknown provider or canonical identities fail closed.
Step 6.2 implements this resolution against exact registry evidence and rejects
conflicting ID/name mappings.

## Request and response boundaries

Each capability has its own request and response type. Requests include the
explicit scope, compatibility metadata and typed page request. Capability-only
filters are limited to:

- optional UTC `updated_since` for fixture observations;
- a unique, sorted tuple of known provider fixture IDs for status reads; and
- optional UTC `completed_since` for result observations.

Request identity uses compact, sorted, BOM-free UTF-8 JSON and SHA-256. It
contains no endpoint URL, authentication header, token, password or other
credential. Pagination cursors are opaque and must advance.

Typed response envelopes contain:

- the exact request identity bytes and checksum;
- the exact unmodified provider response body and checksum;
- HTTP status, media type, encoding, ETag and Last-Modified metadata;
- UTC retrieval and optional provider-generation timestamps;
- compatibility, page and quota metadata; and
- canonically ordered typed items.

A typed success response requires an HTTP 2xx status. The provider-generated
timestamp cannot follow retrieval. The response capability, source,
compatibility and request cursor must match the exact request identity.
Unmodeled provider fields remain available only in the exact response bytes.

## Time, kickoff and knowledge semantics

All contract instants are timezone-aware UTC. A provider kickoff also declares
an IANA source timezone and source-local date.

- `exact` means the UTC instant converts to the declared local date.
- `date_only` uses local noon only as the deterministic UTC anchor.
- The noon anchor never establishes an intra-day order.
- If any fixture on a source-local competition date is date-only, every
  fixture on that date, including exact-time fixtures, belongs to one
  simultaneous batch.
- Paginated fixture observations cannot be processed chronologically until the
  complete required page set is present.

`retrieved_at`, not an earlier provider timestamp, is the conservative
knowledge boundary. A completed result may update rolling state only for a
later batch whose safe feature cutoff is at or after retrieval. Multiple pages
become usable together only at the latest page retrieval time.

## Fixture status and completion

The provider-neutral status vocabulary is:

| Status | Meaning | Score/result rule |
| --- | --- | --- |
| `scheduled` | Expected future fixture | No official score or outcome |
| `in_progress` | Started but not final | No official full-time score or outcome |
| `postponed` | Nonterminal and reschedulable | Same fixture identity; no score |
| `cancelled` | Terminal non-completion | No score or outcome |
| `abandoned` | Stopped without official completion | Provisional score retained only in exact bytes |
| `finished` | Officially complete | Full-time score and matching outcome required |

Postponement changes kickoff and status revision facts, not stable fixture
identity. Cancellation and abandonment are distinct. Neither is a completed
result. Provider status observations are score-free and only
`CompletedFixtureResult` accepts an official full-time score.

Canonical `FixtureStatus` now represents `abandoned`, but the Step 5.4 database
constraint has not been changed. A later reviewed migration must support that
value before fixture synchronization can persist it.

## Score and standings consistency

Home and away provider teams must differ and must use the same source as the
fixture or result. Completed-result outcome is derived from the non-negative
score and must match it exactly.

Every standings row requires:

- `played = won + drawn + lost`;
- `goal_difference = goals_for - goals_against`; and
- `points = 3 * won + drawn + points_adjustment`.

An explicit signed adjustment represents a reviewed deduction or correction.
An unexplained points discrepancy fails. Within a response page, provider team
IDs and positions are unique and rows are ordered by position then provider
team ID. A later complete-snapshot transformation must verify the expected
20-team population.

## Field authority and predictor policy

Representability never grants predictor eligibility.

| Field family | Authority | Predictor treatment |
| --- | --- | --- |
| Provider IDs and team names | Authoritative external identity | Resolution/control only |
| Kickoff, timezone and precision | Authoritative schedule fact | Chronology/control only |
| Fixture status | Authoritative status fact | Prohibited as same-fixture predictor |
| Official completed score | Authoritative result | Prior state only after knowledge cutoff |
| Standings snapshot | Authoritative reconciliation snapshot | Requires a future reviewed predictor schema |
| Round, venue, referee, codes and provider timestamps | Optional | Requires a future reviewed predictor schema |
| Unmodeled provider fields | Retained-only exact bytes | Prohibited |
| Betting odds and bookmaker markets | Retained-only exact bytes | Prohibited |

The existing `epl-pre-match` version-2 predictor schema remains the only
approved 175-name predictor boundary. Current-provider contracts do not add a
predictor, copy a standings snapshot into predictors or admit odds. Results
remain separate from predictors and can affect only later point-in-time state.

## Pagination, quota and errors

`PageRequest` and `PageMetadata` define positive bounded page sizes, opaque
cursors, returned counts and explicit completion. `QuotaMetadata` distinguishes
`unknown`, `unlimited`, `available` and `exhausted`; bounded quotas reconcile
limit and remaining values and exhausted quotas require reset or retry timing.

`ProviderError` is a sanitized structure with a capability, stable error code,
UTC occurrence time and retry disposition. Its vocabulary covers unsupported
or unavailable capabilities, invalid requests, unknown identities,
authentication and permission failures, missing resources, rate and quota
limits, timeouts, transport failures, provider rejection, malformed or
incompatible responses, integrity failure and unexpected provider failure.

The error contract contains no raw body, URL, request headers or credentials.
`ProviderOperationError` exposes only its safe message and typed detail. Step
6.3 implements secret-header authentication, quota decisions, bounded retry
behavior and sanitized logging through a provider-neutral HTTPS executor.

## Existing provider-cache projection

Step 6.1 defined the mapping below and Step 6.4 now persists it through the
existing `provider_cache.response` table:

| Current capability | Cache capability |
| --- | --- |
| `current_season_teams` | `metadata` |
| `current_season_fixtures` | `fixtures` |
| `fixture_status` | `fixtures` |
| `completed_results` | `results` |
| `standings` | `standings` |

The exact credential-free request identity will be a
`lineage.stored_object` using `identity_json_v1`; its checksum maps to
`request_identity_sha256`. The exact provider body will be an opaque text
stored object; its checksum maps to `response_sha256`. Retrieval maps to
`fetched_at` and response transport metadata maps directly to the existing
columns.

The response stored object's `format_id` carries the current-provider contract,
provider API and parser-schema compatibility identifiers. Because the exact
operation is also inside the request identity, teams and status requests cannot
collide despite their broader cache capability values.

`deterministic_provider_cache_key` hashes schema version, source, mapped cache
capability, request checksum and retrieval timestamp. Step 6.4 requires explicit
UTC expiry after retrieval and retrieves only the latest matching row whose
freshness window contains the lookup instant.

## Provenance and preserved boundaries

Future canonical fixture revisions must retain the provider fixture reference,
request identity, exact response checksum, retrieval time and compatibility
metadata. Later feature artifacts must preserve that lineage alongside the
complete verified historical context.

Current ingestion cannot bypass historical raw-manifest verification when it
combines with historical state. It cannot access the sealed 2025–26 target,
import production artifacts, activate a model, infer scorelines from CatBoost
probabilities or change chronological evaluation and simulation semantics.

The provider capability protocol remains a port. Step 6.3 supplies only a
generic allowlisted HTTPS executor; no provider-specific endpoint, parser or
vendor configuration is selected.
