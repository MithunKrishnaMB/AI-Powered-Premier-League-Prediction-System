# Neon and Render Backend Release

## Scope and cost boundary

Milestone K Steps 10.3 and 10.4 use a Neon Free PostgreSQL project and one
Render Free Docker web service. Neither account should contain payment details,
and every selected resource must show a zero price before it is created. Free
services have quotas, no production service-level guarantee and idle wake-up
latency. Do not add a keep-alive request, scheduler, recurring monitor or other
traffic intended to defeat scale-to-zero behavior.

This release remains deliberately dark. It creates an empty reviewed schema and
deploys the existing read-only API, but it does not import the production
artifact or historical corpus, select a current-data provider, inspect sealed
2025–26 targets, create final-test evidence, activate a model  or generate a
prediction or simulation. PostgreSQL can become ready while the aggregate
readiness endpoint correctly remains HTTP 503 with `no_active_model`.

## Production connection separation

Use two Neon connection URLs with different roles and purposes:

| Setting | Endpoint | Role | Location |
| --- | --- | --- | --- |
| `PLP_PRODUCTION_MIGRATION_DATABASE_URL` | Direct | Neon owner | Temporary local process or Git-ignored local secret file |
| `PLP_PRODUCTION_DATABASE_URL` | Pooled | `pl_api` read-only login | Render secret and Git-ignored local handoff file |

Both URLs must use `postgresql+psycopg://`, include an explicit port and include
`sslmode=require` (or a stronger verification mode). Neon displays URLs using
`postgresql://`; replace only that leading scheme when configuring this
application. Never place either URL in Git, documentation, command output or a
Render build argument. The migration URL must never be added to Render.

The pooled application hostname contains Neon's `-pooler` suffix. The direct
migration hostname does not. This keeps ordinary requests behind Neon's
PgBouncer boundary while migrations retain stable session behavior.

## Step 10.3 — provision and migrate Neon

1. Create a Free Neon project named `premier-league-prediction-platform` with a
   PostgreSQL version of at least 16 and database name `pl_platform`. Choose the
   available region closest to Render Singapore and record the actual region in
   the closeout evidence.
2. Copy the owner role's direct connection URL into the current local shell as
   `PLP_PRODUCTION_MIGRATION_DATABASE_URL`. Set
   `PLP_ENVIRONMENT=production`. Do not save the value to a tracked file.
3. Inspect the pending graph and apply the reviewed chain once:

   ```powershell
   alembic current
   alembic heads
   alembic upgrade head
   alembic current
   ```

   The only accepted head is `f0010_step_10_5`. Do not downgrade the hosted
   database after provisioning.
4. In Neon's authenticated SQL editor, replace the password placeholder with a
   newly generated value and create the runtime login. The real password must
   exist only in the SQL editor while executing and in Render's secret field:

   ```sql
   CREATE ROLE pl_api WITH
       LOGIN
       PASSWORD '<GENERATE_A_UNIQUE_PASSWORD>'
       NOSUPERUSER
       NOCREATEDB
       NOCREATEROLE
       NOINHERIT
       NOREPLICATION
       NOBYPASSRLS;
   ```

5. Still as the migration owner, grant only the read surface required by the
   GET-only API:

   ```sql
   GRANT CONNECT ON DATABASE pl_platform TO pl_api;
   GRANT USAGE ON SCHEMA
       public,
       persistence,
       lineage,
       identity,
       football,
       feature,
       model,
       registry,
       ml,
       ingestion,
       provider_cache,
       simulation,
       prediction
   TO pl_api;

   GRANT SELECT ON ALL TABLES IN SCHEMA
       public,
       persistence,
       lineage,
       identity,
       football,
       feature,
       model,
       registry,
       ml,
       ingestion,
       provider_cache,
       simulation,
       prediction
   TO pl_api;

   ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO pl_api;
   ```

6. Build a pooled Neon URL for `pl_api`, configure it temporarily as
   `PLP_PRODUCTION_DATABASE_URL` and run:

   ```powershell
   plp-check-database --target production
   ```

   The sanitized result must report the intended database and `pl_api`, UTC,
   PostgreSQL 16 or newer and no superuser, database-creation, role-creation,
   replication or row-security-bypass capability. Confirm separately that
   `alembic_version` contains only the reviewed release head.
7. Remove both URLs from the local process after verification. Retain the
   owner URL only in Neon's credential controls, a user-managed password
   manager or the Git-ignored local `.env`; do not provide it to Render. The
   pooled URL may remain in a user-managed password manager or Git-ignored
   local `.env` for manual verification. Never copy either value into tracked
   content.

### Verified Neon result (2026-09-23)

The Free project is provisioned in AWS Asia Pacific 1 (Singapore) with
PostgreSQL 18.6, branch `production` and database `pl_platform`. Alembic reached
`f0010_step_10_5`. The pooled `pl_api` login reports UTC, can select all 111
application relations, has zero relation write privileges and has no elevated role
capability. No corpus, registry state, artifact, provider data, prediction,
simulation or sealed target was imported or inspected.

## Step 10.4 — deploy Render manually

The tracked `render.yaml` defines exactly one Docker web service:

- Free plan, Singapore region and one instance;
- automatic deploys and preview environments disabled;
- no database, disk, worker, cron job, build-time secret or pre-deploy command;
- `/health/live` as the Render health check;
- a runtime-only prompt for `PLP_PRODUCTION_DATABASE_URL`; and
- bounded SQLAlchemy pooling suitable for one Uvicorn worker.

The source commit must be available to Render through a repository URL before a
Blueprint can be created. Because repository staging, commits and pushes are
user-controlled, create or update that remote only after reviewing the local
diff. In Render, create a Blueprint from that exact commit, verify that the
service plan says Free and the region says Singapore, enter only the pooled
`pl_api` URL when prompted and leave auto-deploy disabled.

Render terminates TLS at its edge and overwrites `CF-Connecting-IP` with the
client address. The deployment explicitly trusts only that single validated
header for rate-limit identity. Uvicorn continues to reject generic proxy
headers, so caller-controlled `X-Forwarded-For` values cannot alter the client
identity.

After the manual deployment completes, verify the public HTTPS endpoint:

1. `/health/live` returns HTTP 200 and the stable liveness body.
2. `/health/ready` returns HTTP 503 with PostgreSQL `ready` and active model
   `no_active_model`.
3. `/openapi.json` contains exactly sixteen paths and GET operations only.
4. A supplied valid `X-Request-ID` is echoed and every response retains the
   security headers, including production HSTS.
5. Resource reads operate against the empty migrated database without any
   corpus import and the sealed season remains inaccessible.
6. No secret appears in Render build logs, runtime logs or the checked-in
   Blueprint.

### Verified Render result (2026-09-23)

One Render Free Docker web service is live in Singapore at
`https://premier-league-prediction-api.onrender.com`. Service
`srv-dap79enf3r2c73a0npfg` has automatic deploys off and `/health/live` as the
platform health check. Final manual deployment `dep-dapl3f3bc2fs73b49lu0`
built commit `569504f2775c2e6092a956248266a9052e584a66` successfully and
reached Live in 2m30s. Exactly these seven
runtime settings remain:

- `PLP_DATABASE_CONNECT_TIMEOUT_SECONDS`;
- `PLP_DATABASE_MAX_OVERFLOW`;
- `PLP_DATABASE_POOL_SIZE`;
- `PLP_ENVIRONMENT`;
- `PLP_LOG_LEVEL`;
- `PLP_PRODUCTION_DATABASE_URL`; and
- `PLP_TRUSTED_CLIENT_IP_HEADER`.

Duplicate obsolete production-database entries were removed. Only the pooled
read-only `pl_api` URL is stored in Render; the owner migration URL was never
sent. Any credential that became visible during setup was immediately revoked,
and the final value was rotated after that exposure and fingerprint-verified
without printing it or placing it in tracked content.

Public verification returned HTTP 200 from `/health/live`. `/health/ready`
returned the intentional HTTP 503 with PostgreSQL `ready` and active model
`no_active_model`. An empty team collection preserved offset pagination; a
missing team returned the uniform HTTP 404 envelope and an invalid limit
returned the uniform HTTP 422 validation envelope. `/openapi.json` exposed
exactly sixteen GET operations and no mutating operation. Request-ID echo,
HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and
rate-limit headers were present and an untrusted Origin was rejected with
HTTP 403 and no allow-origin header.

### Completed coordinated release

Revision `f0010_step_10_5` was applied with the direct owner URL before Render
deployed the matching published commit. The pooled `pl_api` role was reverified
at the new head before deployment, and the owner URL was never sent to Render.
The public acceptance checks above were then repeated against the new instance.

Do not use `/health/ready` as Render's deployment health check until an active
model is separately authorized and available. Do not add a fake registry,
artifact fallback or synthetic active state to make readiness return 200.

## Free-tier operational limits

Render Free services sleep after an idle period and can take about a minute to
wake. Neon also suspends idle compute and resumes it on demand. A first request
after inactivity can therefore be materially slower than a warm request. This
is an accepted zero-cost constraint, not a reason to add prohibited keep-alive
automation. Neon Free storage and compute usage must be checked manually before
any later corpus import is authorized.

References:

- [Render free-instance limits](https://render.com/docs/free)
- [Render web services and port binding](https://render.com/docs/web-services)
- [Render health checks](https://render.com/docs/health-checks)
- [Render Blueprint schema](https://render.com/docs/blueprint-spec)
- [Render trusted client address guidance](https://render.com/articles/host-pocketbase-on-render)
- [Neon compute and scale-to-zero behavior](https://neon.com/docs/manage/endpoints/)
- [Neon pooled connections](https://neon.com/blog/postgres-support-case-recap)
