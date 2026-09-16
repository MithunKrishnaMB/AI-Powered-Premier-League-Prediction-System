# Milestone I to J Handoff

## Completed implementation boundary

Milestone I now contains the explicit import-safe FastAPI factory, liveness and
fail-closed readiness, shared request IDs/errors/pagination, all planned
read-only football and model projections, a reviewed OpenAPI 3.1 contract and
factory-scoped HTTP controls.

The published API has exactly two health operations and fourteen version-one
resource operations. All resource operations are GET-only. OpenAPI contract
tests pin paths, operation IDs, response schemas and the absence of mutation
verbs. Swagger UI is available at `/docs`; ReDoc remains disabled.

Browser access is denied by default and uses exact configured origins. Security
headers cover success, error and preflight responses. The bounded process-local
sliding-window limiter uses only direct peer identity, exempts liveness and
preflight and returns stable 429 envelopes and retry metadata.

## Preserved boundaries

- Application import and factory construction open no database connection and
  load no model or artifact.
- Resource queries remain request-scoped, read-only and explicitly isolated
  between development and test PostgreSQL.
- Production has no database fallback and readiness still reports
  `no_active_model` for the actual development-accepted registry.
- No provider was selected or contacted and no production corpus was imported.
- No prediction, scoreline distribution, simulation or metric was generated.
- No sealed 2025–26 target or final-test evidence was inspected.
- No registry state, database row, raw capture or artifact byte was mutated.
- No frontend, deployment, scheduled automation or CI/CD configuration was
  introduced.

## Verification boundary

The complete Python 3.14.7 suite passes 565 tests with 90.69% branch coverage.
It covers the OpenAPI contract, exact-origin normalization and rejection,
successful and rejected preflight, security headers, production-only HSTS,
rate acceptance/exhaustion/recovery, liveness exemption and bounded client
tracking. Live integration checks retain the isolated PostgreSQL and actual
no-active-registry boundaries. Ruff checks 240 formatted Python files, strict
mypy checks 199 source/test/migration files and dependency consistency passes.

Milestone completion still requires the user-owned local closeout commit under
the repository's milestone rule. No files were staged or committed by this
implementation.

## Step 9.1 boundary

Step 9.1 may implement cache-aware live fixture reads using the existing
provider-neutral capability, exact-response cache and immutable synchronization
contracts. It must not select a provider without explicit approval, generate
scoreline distributions, access sealed targets, activate a model or add
deployment, scheduled automation, frontend or CI/CD configuration.
