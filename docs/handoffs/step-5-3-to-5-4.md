# Step 5.3 to 5.4 Handoff

## Completed steps

Milestone F Steps 5.2 and 5.3 are complete. The project has typed, secret-safe,
explicitly isolated development and test PostgreSQL connection settings, a
read-only fail-closed connectivity checker and an initialized Alembic
environment with no revisions.

The local topology is `pl_platform_dev` and `pl_platform_test`, both owned by
the restricted `pl_app` login. The actual password exists only in ignored
`.env`. The tracked example uses `CHANGE_ME`. PostgreSQL URLs are absent from
Alembic configuration, structured logs and checker output.

## Implemented connection contracts

- Python remains exactly 3.14.7; SQLAlchemy, psycopg and Alembic are version
  pinned in `pyproject.toml`.
- Development and test URLs must be complete `postgresql+psycopg` URLs, must
  resolve to different host/port/database targets and are held as `SecretStr`
  values.
- Connection target selection is explicit; test never falls back to
  development.
- The checker requires PostgreSQL 16+, UTC, URL/database/role agreement and a
  login that is not superuser, database creator, role creator, replication
  capable or able to bypass row-level security.
- Engines are lazy, bounded and health checked. Connectivity verification is
  read-only and returns no secret.

## Alembic boundary

- `alembic.ini` contains no database URL.
- `migrations/env.py` selects development or test through typed settings and
  rejects production.
- Online execution uses `NullPool`, UTC and transactions. Type,
  server-default and schema comparison are enabled.
- `migrations/versions/` is intentionally empty. No `alembic_version` table or
  application table was created in Step 5.3.

## Preserved guarantees

No raw, canonical, feature, training, evaluation, model, registry or
simulation artifact was imported or modified. Raw manifest verification was
not bypassed. The 2025–26 test target remains sealed. Predictors and targets
remain separate, chronological evaluation is unchanged, retained betting odds
remain unapproved predictors and team identity remains explicit without fuzzy
matching. CatBoost depth 6, identity calibration and outcome order
`home_win`, `draw`, `away_win` are unchanged. Development acceptance is not
active promotion, no active model exists and classifier probabilities remain
independent of simulation scoreline distributions.

## Verification

- Python: 3.14.7.
- PostgreSQL: 18.4 for both development and test.
- Connection identity: `pl_app` connected only to the explicitly selected
  `pl_platform_dev` or `pl_platform_test` target, with UTC sessions.
- Role audit: login enabled; superuser, database creation, role creation,
  replication and row-security bypass all disabled.
- Database object audit: zero non-system tables in both targets.
- Alembic: empty heads and history; online `current` succeeded without creating
  a version table.
- pytest: 368 passed, including two live PostgreSQL integration tests.
- branch coverage: 90.75%, above the required 90%.
- Ruff lint and formatting, strict mypy across `src`, `tests` and `migrations`,
  dependency consistency and diff whitespace checks passed.

## Exact next step — 5.4

Add the first Alembic revision for identity, season and fixture entities only,
following the keys, immutable artifact projection, fixture-revision model,
cardinalities and fail-closed constraints in the
[PostgreSQL entity-relationship model](../architecture/postgresql-entity-relationship-model.md).

Step 5.4 must not implement the rating, feature, model, prediction, evaluation,
simulation or ingestion/cache tables assigned to Steps 5.5–5.7. It must not
add repositories, import artifacts, persist simulation results, access the
sealed final-test target, activate a model or add APIs, deployment, frontend
or CI/CD configuration.
