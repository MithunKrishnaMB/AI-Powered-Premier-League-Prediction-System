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

## Closeout record

- Steps 8.1 through 8.9 are implemented and documented.
- The final suite passes 565 tests with 90.69% branch coverage on 64-bit Python
  3.14.7.
- Ruff lint/format, strict mypy, dependency, whitespace and local Markdown-link
  checks pass.
- Development and test PostgreSQL remain separate restricted targets at exact
  head `f0009_step_7_9`; API reads do not mutate either target.
- All 11 historical raw captures retain their verified manifest boundary.
- The actual registry remains `development_accepted`, not active and resolves
  to `no_active_model`.
- The production artifact corpus was not imported, the sealed target was not
  inspected and no provider was selected or contacted.
- No files were staged or committed; the local closeout commit remains the
  user's responsibility.

## Step 9.1 boundary

Step 9.1 is implemented as a provider-neutral read-through service over the
existing fixture capability and immutable exact-response cache. It classifies
exact-request cache evidence as fresh, stale or missing, reuses compatible
exact bytes without provider contact and refreshes stale/missing pages only when
the declared fixture capability is supported. Incompatible cache evidence fails
closed. Complete pagination precedes reviewed team resolution and canonical
fixture UUID derivation and ordered page provenance retains request/response
checksums, cache key, compatibility, retrieval and expiry.

No provider was selected or configured. Step 9.1 adds no FastAPI path and does
not synchronize normalized fixture tables, poll, reconcile results, expose job
commands, schedule work, generate predictions or simulations, inspect sealed
targets or mutate registry or artifact state.

Step 9.1 verification passes 579 tests with 90.82% branch coverage on Python
3.14.7. Ruff lint/format checks 244 Python files, strict mypy checks 202
source/test/migration files and dependency consistency passes. PostgreSQL
integration exercises the exact fresh, stale and missing states only against
the isolated test target, while the pinned OpenAPI contract remains sixteen
GET-only operations.

## Steps 9.2 through 9.4 boundary

Step 9.2 adds a pure kickoff-aware policy and a composable
read/synchronize/plan job. Exact kickoff proximity, in-progress, postponed and
terminal state have deterministic bands. Date-only fixtures use the retained
provider-local calendar boundary rather than their noon storage anchor. The
policy returns the earliest next poll but schedules nothing.

Step 9.3 applies the exact-cache fresh/stale/miss rules to completed-result
pages. Fresh compatible bytes require no provider. Stale or missing pages
refresh only through an injected supported capability. Complete pagination,
canonical team/fixture resolution and duplicate checks all precede one
raw-manifest-gated immutable reconciliation write; an empty response is a
no-op. The PostgreSQL prior-fixture, official-score, chronology and idempotence
constraints remain authoritative.

Step 9.4 exposes `plp-current-data poll-fixtures` and
`reconcile-final-matches`. Both require an explicit development/test target,
season and UTC instant. Production is not a target, output/errors are sanitized
JSON and the installed runner fails closed because no provider/runtime
composition has been approved. Imports construct no provider, engine, model or
artifact.

The FastAPI contract remains the same sixteen GET operations with unchanged
request IDs, envelopes, pagination, OpenAPI, CORS, headers and rate limits. No
provider, scheduler, GitHub Actions, CI/CD substitute, credentials, prediction,
simulation, retraining, registry transition, sealed-target evidence, production
artifact, frontend or deployment configuration was introduced.

The former Step 9.5 scheduling item has been removed from the roadmap and was
not implemented. No scheduler, CI/CD, GitHub Actions or DevOps substitute was
added. Candidate retraining became Step 9.5; comparison/promotion reporting and
monitoring documentation were renumbered to Steps 9.6 and 9.7.

The complete Python 3.14.7 suite now passes 617 tests with 91.08% branch
coverage. Ruff lint/format checks 255 Python files, strict mypy checks 212
source/test/migration files, dependency consistency and whitespace checks pass,
and the live PostgreSQL suite verifies cache-backed final reconciliation and
idempotence against the isolated test target. The OpenAPI contract remains
sixteen GET-only operations. No changes were staged or committed.

## Step 9.5 candidate-retraining boundary

Step 9.5 is an explicitly invoked in-memory workflow, not an automated job. It
derives a baseline from an exact verified artifact manifest, requires only the
accepted 2015–16 through 2024–25 development examples and pairs each immutable
operational pre-match feature with exactly one official post-kickoff result.
The sealed 2025–26 target is rejected and remains unread.

The workflow refits the fixed deterministic CatBoost depth-6 policy and returns
the classifier with a UUIDv5-identified, checksummed
`candidate_unassessed` manifest. The manifest binds baseline lineage, predictor
schema, exact baseline/operational/combined training checksums, operational
feature/result/cache identities and the result-retrieval knowledge cutoff.

No candidate bytes are written to the production artifact corpus. No registry
entry or event is created or changed, no model is compared or promoted and no
prediction, scoreline distribution, simulation or final-test metric is
generated. The actual registry remains `development_accepted`, not active.
Step 9.6 may add a comparison and promotion report only after separate approval.

The complete Python 3.14.7 suite through Step 9.5 passes 630 tests with 91.04%
branch coverage. Ruff lint/format checks 260 Python files, strict mypy checks
216 source/test/migration files and dependency and whitespace checks pass.
The new unit and canonical-contract tests cover exact baseline verification,
one-to-one operational pairing, sealed-target rejection, chronology, schema and
identity failures, deterministic fitting inputs and the absence of promotion or
registry fields. No files were staged or committed.
