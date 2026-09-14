# Step 6.4 to Step 6.5 Handoff

## Completed boundary

Steps 6.2 through 6.4 now provide pure current-team/current-fixture
transformation, provider-neutral secret-safe HTTPS execution and immutable exact
response caching. Current and historical adapters share stable canonical
fixture UUID derivation. Unknown or conflicting identities fail without fuzzy
matching and date-only provider-local dates remain simultaneous batches.

The generic client has no configured vendor. It permits only exactly
allowlisted HTTPS hosts, keeps authentication outside request identity and
logs, disables redirects, bounds retries and response bytes and gates exhausted
quota. Cache writes preserve separate request/response bytes and checksums
through the raw-manifest-gated aggregate repository; latest-fresh reads
revalidate identity, provenance and compatibility.

## Exact next step — 6.5

Synchronize transformed fixtures idempotently into the canonical PostgreSQL
fixture, revision, source-reference and batch structures.

Step 6.5 must:

- add a reviewed migration for `abandoned` before persisting that status;
- reuse the existing canonical fixture UUID without incorporating provider ID,
  kickoff or status;
- create immutable revisions for genuine kickoff/status changes and make an
  identical replay a no-op;
- retain the provider fixture reference, exact request/response checksums,
  retrieval timestamp and compatibility needed to trace each revision;
- construct whole-local-date batches when any fixture on that date is
  date-only;
- reject unknown teams, cross-season scope, regressive or inconsistent state
  and conflicting provider references; and
- verify the historical raw manifest before any aggregate write.

Step 6.5 must not reconcile completed results, synchronize standings, ingest
squads or players, import production artifacts, access the sealed final-test
target, promote a model, add APIs, deploy, create frontend code or configure
CI/CD.

The implemented integration boundary is documented in
[Current-Provider Transformations, Transport and Caching](../data/current-provider-integration.md).
