# Current-Provider Transformations, Transport and Caching

## Implemented scope

Steps 6.2 through 6.4 implement three provider-neutral layers over the Step 6.1
contracts:

1. pure team and fixture transformation;
2. allowlisted HTTPS execution with authentication, quota and retry policy; and
3. immutable PostgreSQL response caching.

No vendor, endpoint, credential or provider-specific payload parser is selected
by the repository. Fixture synchronization, completed-result reconciliation and
standings ingestion are implemented separately in Steps 6.5 through 6.7;
optional squads, players and offline recorded-response contracts are
implemented separately in Steps 6.8 and 6.9.

## Step 6.2 transformation

`TeamRegistry` indexes reviewed `(source_id, external_id)` values separately
from normalized reviewed aliases. A current team may resolve through either
piece of evidence. If both exist and identify different canonical teams, the
observation fails. An unknown ID/name pair also fails; no similarity or fuzzy
matching path exists.

`transform_current_teams` verifies the explicit canonical competition/season,
requires every resolved team to belong to that reviewed season and preserves
the complete response capture with each resolution. Duplicate canonical
resolutions fail.

`transform_current_fixtures` resolves both provider team IDs before deriving a
canonical fixture. Historical and current ingestion now share
`canonical_fixture_id`, whose UUIDv5 input is canonical competition, season,
home team and away team. Kickoff changes and postponements therefore create new
facts for the same fixture identity. The output retains the provider fixture
reference, source-local date/timezone, provider update time and exact capture.

Finished fixture observations are deliberately rejected by this step because a
canonical finished fixture requires the separately reconciled official result
owned by Step 6.6. Scheduled, in-progress, postponed, cancelled and abandoned
score-free observations remain representable.

`current_fixture_batches` groups using the retained provider-local date. Any
date containing one `date_only` observation absorbs every exact-time fixture on
that date into one UUID-ordered batch. Exact-only dates group by identical UTC
kickoff. Each batch retains the latest response retrieval time as its knowledge
availability boundary.

## Step 6.3 HTTPS, authentication, quota and retry

`ProviderEndpointRequest` requires HTTPS, an exactly allowlisted host, no URL
userinfo or fragment and no credential-like query parameter. Request identity
remains the Step 6.1 canonical credential-free JSON. Public headers cannot use
credential-bearing names; authentication is a separate `SecretStr` header
contract and prepared-request representations omit headers.

`UrllibProviderTransport` uses standard TLS behavior, disables redirects,
enforces caller-supplied timeout and maximum-body limits and returns exact body
bytes plus selected response metadata. It never logs URLs, headers, bodies or
exception text.

`CurrentProviderRequestExecutor`:

- checks recorded quota state before transport;
- retries only timeout, transport, rate-limit and temporary-provider failures;
- never retries invalid requests, authentication, permission, missing-resource
  or other permanent provider rejection;
- caps attempts at five and applies deterministic bounded exponential or
  `Retry-After` delays;
- conservatively blocks an exhausted capability until every declared reset
  boundary has passed; and
- logs only source, capability, request checksum, attempt, typed error,
  disposition and retry decision.

Successful transport output becomes `ProviderResponseCapture` through
`capture_successful_transport_response`, which computes the exact body checksum
and binds retrieval, compatibility, pagination, quota and provider request
metadata before parsing or caching.

## Step 6.4 immutable PostgreSQL cache

`provider_cache_write_plan` maps one validated capture into:

- canonical credential-free request bytes under `identity_json_v1`;
- the exact unmodified provider body under `opaque`; and
- one immutable `provider_cache.response` projection.

The existing `f0004_step_5_7` schema is sufficient, so Step 6.4 adds no Alembic
revision. Cache identity remains derived from contract version, source, mapped
cache capability, request checksum and UTC retrieval time. Expiry must be an
explicit UTC instant strictly after retrieval.

`ProviderCacheRepository.store` uses the established raw-manifest-gated,
serializable aggregate writer. The historical manifest is verified before the
database transaction even though the cache payload is current-season data.
Identical writes are idempotent and conflicts fail closed.

`get_latest_fresh` selects by source, mapped cache capability and exact request
checksum, then requires `fetched_at <= lookup < expires_at`. It reloads both
stored byte streams and revalidates their checksums, deterministic cache key,
exact operation, source, media metadata and compatibility format. Expired or
missing entries return no value; stale data is never silently served as fresh.

## Preserved ML and lifecycle boundaries

These steps do not change the approved 175 predictors, ingest betting odds,
open the sealed 2025–26 target, import the production artifact corpus, calculate
a final-test metric or activate a model. They do not derive scorelines from the
CatBoost three-way probabilities or change identity calibration, outcome order,
chronological evaluation, 10,000-run simulation behavior, numerical dtypes or
position-mass guarantees.
