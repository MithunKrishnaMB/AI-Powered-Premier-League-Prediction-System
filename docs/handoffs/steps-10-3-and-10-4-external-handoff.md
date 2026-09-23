# Steps 10.3 and 10.4 External Handoff

## Completed boundary

The approved Neon Free and Render Free release is complete. Production
PostgreSQL is an explicit TLS-only target with separate runtime and migration
credentials. The API uses a pooled, unprivileged read-only role; Alembic uses
a direct owner URL only from a manual local process. Render runs one Free
Singapore Docker web service with manual deploys, one worker, no disk, no
worker or cron resource, dynamic port binding and liveness health.

Python 3.14.7 passes 666 tests with no skips and 91.10% branch coverage. Ruff,
strict mypy over 230 files and dependency consistency pass. No dependency was
added. Development/test isolation, the nine-revision chain, all historical raw
manifest checks, the sixteen GET-only operations and all transport controls are
preserved.

## Verified external state

- GitHub: commit `461f31f637ad9bbe52eb07917bf5771606ee5c54` is available
  on `main` in the public project repository.
- Neon: the Free project `premier-league-prediction-platform` exists in AWS
  Asia Pacific 1 (Singapore), with production branch `production`, database
  `pl_platform` and PostgreSQL 18.6 in UTC. The schema is at
  `f0009_step_7_9`.
- Neon role: pooled `pl_api` access was verified against 111 of 111 migrated
  tables, with zero table write privileges and superuser, database creation,
  role creation, inheritance, replication and row-security bypass all false.
- Render: one Free Docker web service is live in Singapore at
  `https://premier-league-prediction-api.onrender.com`. Service
  `srv-dap79enf3r2c73a0npfg` has auto-deploy off and `/health/live` as its
  platform health check. Final manual deployment `dep-dapb3qnf3r2c73c30ojg`
  built commit `461f31f` successfully in 59.7 seconds.
- Render configuration: exactly seven reviewed environment variables remain.
  Duplicate obsolete production-database entries were deleted. The only
  database secret sent to Render is the pooled `pl_api` runtime URL; the direct
  owner migration URL was never sent.
- Secret recovery: credentials that became visible during setup were revoked
  before the final runtime credential was installed. The final value was
  fingerprint-verified without printing it and remains only in secret stores
  or Git-ignored local configuration. Temporary upload files were removed.
- Public acceptance: liveness returns HTTP 200. Readiness intentionally returns
  HTTP 503 with PostgreSQL `ready` and active model `no_active_model`.
  `/openapi.json` contains exactly sixteen GET operations. Empty pagination,
  request-ID echo, uniform 404 and 422 envelopes, production security headers,
  rate-limit headers and rejection of an untrusted CORS origin were verified.
- Docker: the CLI was not available in the current shell, so the updated
  image was not rebuilt again. The completed Step 10.2 image evidence and the
  successful Render build from the exact published commit remain authoritative.

## Closeout and handoff outcome

Steps 10.3 and 10.4 are complete. No corpus or production artifact was
imported, no current-data provider was contacted, no registry entry was
mutated, no prediction or simulation was generated and the sealed 2025–26
target was not inspected. The actual registry remains
`development_accepted` with no active model.

This handoff was accepted and Steps 10.5 and 10.6 are now complete locally.
Their current release evidence and exact next boundary are recorded in
[Step 10.6 to 10.7 handoff](step-10-6-to-10-7.md). No keep-alive traffic,
scheduling, recurring monitor, CI/CD, GitHub Action or infrastructure
substitute was added.
