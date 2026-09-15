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
- `PLP_ENVIRONMENT=production` fails closed because production migration policy
  is outside Steps 5.2 and 5.3.

Online migrations use a non-pooled connection with a forced UTC session.
Offline rendering uses the same explicitly selected URL. Type and server-default
comparison, all-schema inspection and per-migration transactions are enabled.
An externally supplied Alembic connection remains supported for later
transactional migration tests.

Step 5.3 itself introduced no revision or database object. Steps 5.4 through
5.7 subsequently added the baseline schema; Steps 6.7–6.8 and 7.2–7.4 extend
the same linear transactional chain with current-season, squad and prediction-
lifecycle structures. The current head is `f0007_step_7_4`; the allocation and
reviewed commands are
documented in the [migration chain](postgresql-migrations.md).

## Preserved boundaries

Connection and migration initialization do not import artifacts, bypass source
manifest verification, open the sealed 2025–26 target, persist a simulation,
create a repository, calculate a final-test metric or promote an active model.
No active model exists. The Python 3.14.7, predictor, compatibility, numerical,
canonical-byte, checksum and provenance contracts remain unchanged.
