# Cache-Aware Live Fixture Reads

## Scope

Step 9.1 adds a provider-neutral read-through boundary for complete current-
season fixture responses. It composes the existing typed fixture request and
response contracts, immutable PostgreSQL exact-response cache, reviewed team
resolution and canonical fixture transformation. It does not select a provider,
add an HTTP endpoint, schedule a poll or persist normalized fixture revisions.

The caller supplies an explicit `CurrentSeasonFixturesRequest`, reviewed
`CurrentTeamResolution`, canonical `PremierLeagueSeason`, UTC lookup instant,
positive cache TTL, exact-cache access, cached-response decoder and optional
provider. No dependency is discovered or contacted during module import.

## Exact cache state

The cache repository now classifies the latest exact source, capability and
request-identity match known by the lookup instant as `fresh`, `stale` or
`miss`. It reloads the request and response objects and revalidates their bytes,
checksums, deterministic cache key, media metadata and pinned compatibility
before returning an entry. Lookup transactions are read-only and require exact
Alembic head `f0009_step_7_9`.

- A fresh compatible entry is decoded from its exact stored response bytes.
  The provider and its capability manifest are not consulted.
- A stale entry is never served. It is refreshed only when the provider is
  configured and declares the fixture capability supported.
- A miss follows the same supported-provider refresh path.
- A corrupt or incompatible entry fails closed and is not hidden by a provider
  fallback.
- Unsupported, temporarily unavailable and unconfigured providers produce
  distinct sanitized failures when a refresh is required.

Successful refreshes are stored through `ProviderCacheRepository`, so the
historical raw-manifest gate runs before the serializable exact-byte cache
write. Expiry is the provider retrieval time plus the caller's explicit TTL.
No provider credential, URL or raw failure enters cache identity, provenance or
failure text.

## Pagination and canonicalization

Reads must begin at the first provider page. Every page has its own canonical
credential-free request identity and independent cache decision. The reader
follows advancing cursors until the typed response declares completion, rejects
cycles and returns no fixture collection after a partial failure.

Only after the full page set is valid are provider observations transformed
through `transform_current_fixtures`. Reviewed external team evidence supplies
canonical teams and the existing competition, season, home-team and away-team
UUIDv5 rule supplies fixture identity. Duplicate provider or canonical fixture
identities across pages fail closed. Results are ordered by kickoff and fixture
UUID and retain ordered page provenance containing cache key, request and
response checksums, retrieval, expiry, compatibility and cache decision.

## Preserved boundaries

Step 9.1 deliberately stops before fixture synchronization. Step 9.2 now
composes it through `FixturePollingJob`, which persists only a complete
non-empty read and evaluates the pure kickoff-aware policy. The reader itself,
current fixture batch rules and FastAPI projections remain unchanged. Neither
layer schedules future execution.

The FastAPI surface remains the same sixteen GET operations. Request IDs,
sanitized errors, offset pagination, OpenAPI, CORS, security headers and rate
limits are unchanged. Development and test database targets remain explicit and
separate; no production database or provider fallback exists. No model,
registry, prediction, scoreline, simulation, sealed target, production artifact
corpus, frontend, deployment or CI/CD state is read or changed.
