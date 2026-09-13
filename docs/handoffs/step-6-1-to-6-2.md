# Step 6.1 to Step 6.2 Handoff

## Completed boundary

Step 6.1 defines immutable provider-neutral contracts for current-season teams,
fixtures, fixture status, completed results and standings. It includes typed
capability availability, pagination, quota, response metadata, provenance,
compatibility and sanitized errors. Exact request and provider response bytes
have deterministic checksums and a documented mapping to the existing cache
schema, but no response has been persisted.

Provider competition, season, team and fixture identifiers remain separate
from canonical platform identities. Alias or external-ID resolution must be
explicit and reviewed; unknown identities fail and fuzzy matching is
prohibited.

Fixture status now distinguishes cancellation from abandonment. Only
`finished` is completion, and only an official completed result may contain a
full-time score. Date-only kickoff precision retains the whole-local-date
simultaneous-batch boundary, and retrieval time is the conservative knowledge
cutoff.

## Verification boundary

- Runtime remains 64-bit Python 3.14.7.
- The complete suite passes with 409 tests and 90.76% branch coverage, including
  live PostgreSQL migration and repository transaction checks.
- Ruff formatting and lint, strict mypy and dependency consistency pass.
- Current-provider contracts are strict, frozen Pydantic models.
- Request and cache identities are content-derived SHA-256 values.
- Exact provider bytes are retained independently of parsed observations.
- The 175-name predictor schema is unchanged and odds remain prohibited.
- No provider, adapter, client, credentials, retry, cache write, database row,
  production artifact, final-test evidence or active model was introduced.

## Exact next step — 6.2

Implement fixture/team adapter transformations from these provider-neutral
observations into existing canonical identities and fixture revisions.

Step 6.2 must:

- resolve every provider team through reviewed exact alias or external-ID
  evidence and fail on an unknown identity;
- verify the explicit canonical competition and season scope;
- derive the existing canonical fixture UUID only after both teams resolve;
- preserve provider fixture references and complete response provenance;
- preserve UTC, source timezone, kickoff precision, postponement, cancellation,
  abandonment and completion semantics;
- preserve whole-date simultaneous batches whenever a date-only fixture is
  present;
- keep completed scores separate from pre-match fixture observations and
  predictors; and
- produce deterministic canonical ordering without making network or database
  calls.

Step 6.2 must not add network clients, authentication, retries, quota handling,
database caching, synchronization, reconciliation, standings ingestion,
squads, players, production artifact import, final-test evaluation, active
promotion, APIs, deployment, frontend code or CI/CD configuration.

The normative contract is documented in
[Current-Provider Capability and Domain Contracts](../data/current-provider-contracts.md).
