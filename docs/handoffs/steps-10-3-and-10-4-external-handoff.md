# Steps 10.3 and 10.4 External Handoff

## Completed local boundary

The approved Neon Free and Render Free release design is implemented locally.
Production PostgreSQL is an explicit TLS-only target with separate runtime and
migration credentials. The API uses a pooled, unprivileged read-only role;
Alembic uses a direct owner URL only from a manual local process. Render is
defined as one Free Singapore Docker service with manual deploys, one worker,
no disk, no worker or cron resource, dynamic port binding and liveness health.

Python 3.14.7 passes 666 tests with no skips and 91.10% branch coverage. Ruff,
strict mypy over 230 files and dependency consistency pass. No dependency was
added. Development/test isolation, the nine-revision chain, all historical raw
manifest checks, the sixteen GET-only operations and all transport controls are
preserved.

## External state

- Neon: the Free project `premier-league-prediction-platform` exists in AWS
  Asia Pacific 1 (Singapore), with production branch `production`, database
  `pl_platform` and PostgreSQL 18.6 in UTC. The schema is at
  `f0009_step_7_9`.
- Neon role: pooled `pl_api` access was verified against 111 of 111 migrated
  tables, with zero table write privileges and superuser, database creation,
  role creation, inheritance, replication and row-security bypass all false.
- Secrets: the direct owner and pooled runtime URLs are retained only in the
  Git-ignored local `.env`; neither value appears in tracked files or output.
- Render dashboard: authenticated and waiting at web-service source selection;
  no service exists and no Neon credential has been transmitted to Render.
- Git: the repository has no remote and the approved implementation is
  intentionally unstaged and uncommitted.
- Docker: the CLI was not available in the current shell, so the updated
  Render-port image could not be rebuilt in this continuation. The previously
  completed Step 10.2 image evidence remains recorded.

## Required user-owned continuation

1. Review and commit the local changes, then make that exact commit available
   to Render through a repository or immutable public image. Codex must not
   stage, commit or publish it under the current instruction.
2. In Render, create the Blueprint only after confirming Free and Singapore,
   and enter only the pooled `pl_api` URL as the prompted secret.
3. Record the public Render verification without logging either connection
   URL.

Do not start Step 10.5, import a corpus, synthesize an active model, select a
current-data provider, inspect the sealed target, add keep-alive traffic or add
CI/CD while this handoff is open.
