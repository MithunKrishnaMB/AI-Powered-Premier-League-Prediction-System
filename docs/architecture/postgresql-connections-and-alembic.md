# PostgreSQL Connections and Alembic Boundary

## Supported local topology

Milestone F uses the locally installed PostgreSQL server through SQLAlchemy
2.0 and psycopg 3. Development and tests are isolated at the database boundary:

| Target | Database | Login role | URL setting |
| --- | --- | --- | --- |
| Development | `pl_platform_dev` | `pl_app` | `PLP_DATABASE_URL` |
| Test | `pl_platform_test` | `pl_app` | `PLP_TEST_DATABASE_URL` |

`pl_app` is a login role with `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
`NOREPLICATION` and `NOBYPASSRLS`. It owns both local databases so later
migrations can manage their schemas, but it has no cluster-administration
authority. The local password is present only in the ignored `.env`;
`.env.example`, Alembic files, logs and documentation contain no usable
password.

The connection checker verifies the selected database name and role, server
version 16 or newer, a UTC session and the unprivileged role flags, including
row-security bypass. Target selection is explicit and a missing URL, shared
development/test database target, wrong driver scheme, identity mismatch,
privileged login, old server or non-UTC session fails closed. SQLAlchemy
engines are lazy and use connection health checking, a five-second default
timeout and bounded pooling.

## Hosted production topology

Milestone K Step 10.3 adds a separate, fail-closed Neon production boundary:

| Purpose | Target/setting | Endpoint and authority |
| --- | --- | --- |
| API reads | `production` / `PLP_PRODUCTION_DATABASE_URL` | Pooled TLS URL, unprivileged `pl_api` login |
| Alembic | `PLP_PRODUCTION_MIGRATION_DATABASE_URL` | Direct TLS URL, Neon owner, local process only |

Production URLs must use `postgresql+psycopg`, provide complete credentials and
database identity, and include `sslmode=require` or a stronger verification
mode. The runtime URL remains distinct from development and test targets. A
missing runtime or migration URL fails closed rather than falling back to a
local target.

The direct migration credential is never supplied to Render. The deployed API
receives only the pooled `pl_api` URL, checks the same unprivileged-role flags
as local targets and opens each resource transaction as read-only. Alembic
selects the migration URL only when `PLP_ENVIRONMENT=production`; development
and test selection is unchanged. See the
[Neon and Render release runbook](../operations/neon-render-backend-release.md)
for the manual grant and verification sequence.

## Local administrator bootstrap

The one-time cluster bootstrap must be run as an existing PostgreSQL
administrator. It creates or hardens `pl_app`, then creates distinct UTF-8
databases owned by that role. Use the password chosen for the ignored `.env` in
the administrator session; do not place it in a tracked SQL or shell file.

From an authenticated `psql` session, a fresh local cluster is bootstrapped
with:

```sql
CREATE ROLE pl_app
WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password pl_app

CREATE DATABASE pl_platform_dev
WITH OWNER = pl_app ENCODING = 'UTF8' TEMPLATE = template0;
CREATE DATABASE pl_platform_test
WITH OWNER = pl_app ENCODING = 'UTF8' TEMPLATE = template0;

ALTER DATABASE pl_platform_dev SET timezone TO 'UTC';
ALTER DATABASE pl_platform_test SET timezone TO 'UTC';
REVOKE ALL ON DATABASE pl_platform_dev FROM PUBLIC;
REVOKE ALL ON DATABASE pl_platform_test FROM PUBLIC;
```

The `\password` meta-command prompts without placing the application password
in SQL history. Existing roles or databases must be inspected and reconciled
explicitly rather than silently dropped or replaced.

After bootstrap, both targets are verified without changing database state:

```powershell
plp-check-database --target development
plp-check-database --target test
```

The command emits only the target, database and role names, PostgreSQL version
and timezone. It never prints a URL or password.

## Alembic initialization

`alembic.ini` contains the migration script location and logging only. It has
no `sqlalchemy.url`. `migrations/env.py` reads typed settings at runtime:

- `PLP_ENVIRONMENT=development` selects `PLP_DATABASE_URL`;
- `PLP_ENVIRONMENT=test` selects `PLP_TEST_DATABASE_URL`; and
- `PLP_ENVIRONMENT=production` selects the separately authorized
  `PLP_PRODUCTION_MIGRATION_DATABASE_URL`.

Online migrations use a non-pooled connection with a forced UTC session.
Offline rendering uses the same explicitly selected URL. Type and server-default
comparison, all-schema inspection and per-migration transactions are enabled.
An externally supplied Alembic connection remains supported for later
transactional migration tests.

Step 5.3 itself introduced no revision or database object. Steps 5.4 through
5.7 subsequently added the baseline schema; Steps 6.7–6.8 and 7.2–7.4 extend
the same linear transactional chain with current-season, squad and prediction-
lifecycle and post-match workflow structures. The current head is
`f0009_step_7_9`; the allocation and
reviewed commands are
documented in the [migration chain](postgresql-migrations.md).

## Local release gate

Step 10.1 adds an explicit `pytest --cov --require-local-release` mode. Before
the release-only checks run, it requires both configured URLs, verifies that
they resolve to distinct `pl_platform_dev` and `pl_platform_test` databases,
reuses the restricted-role and UTC checks and requires exact head
`f0009_step_7_9` on both targets. Missing or incompatible local evidence is a
failure in this mode rather than a PostgreSQL test skip.

The executable migration cycle validates the target identity before changing
schema state, supplies only a `pl_platform_test` connection to Alembic and
performs all downgrade and incremental upgrade operations inside one caller-
owned outer transaction. Rolling that transaction back restores the original
test database. The development target is read only and its unchanged head is
checked after the cycle. No production target or fallback exists.

## Preserved boundaries

Connection and migration initialization do not import artifacts, bypass source
manifest verification, open the sealed 2025–26 target, persist a simulation,
create a repository, calculate a final-test metric or promote an active model.
No active model exists. The Python 3.14.7, predictor, compatibility, numerical,
canonical-byte, checksum and provenance contracts remain unchanged.
