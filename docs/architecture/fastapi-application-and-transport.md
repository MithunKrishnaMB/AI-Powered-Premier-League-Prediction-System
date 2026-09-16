# FastAPI Application and Transport Boundary

## Scope

Steps 8.1 and 8.2 establish the API process and transport contracts without
adding football-domain endpoints. The boundary contains an explicit application
factory, liveness and readiness routes, request IDs, uniform error envelopes and
reusable offset-pagination schemas.

It does not query teams, seasons, fixtures, standings, predictions,
simulations, model metrics or performance data. It does not select or contact a
current-data provider, generate an output, import an artifact corpus, inspect
the sealed 2025–26 target or mutate registry or persistence state.

## Application construction

`pl_platform.api.create_app` is the only application-construction entry point.
There is no module-level application instance. Importing the API package does
not load settings, create an engine, open a connection, inspect a registry or
load CatBoost.

Calling the factory resolves immutable settings and constructs dependency
probe objects, but it still performs no external I/O. Readiness probes run only
when `GET /health/ready` is requested. The factory accepts an injected typed
readiness service so tests can exercise the complete HTTP boundary without
using process-global overrides.

Steps 8.1 and 8.2 initially kept OpenAPI and interactive documentation routes
disabled. Step 8.8 now publishes the reviewed contract at `/openapi.json` and
Swagger UI at `/docs`; ReDoc remains disabled. No ASGI server or deployment
entry point is introduced.

## Health endpoints

### `GET /health/live`

Liveness returns HTTP 200 with exactly:

```json
{"schema_version":1,"status":"alive"}
```

It proves only that the ASGI process can answer. It never checks settings,
PostgreSQL, providers, registry state, artifact bytes or model availability.

### `GET /health/ready`

Readiness reports required dependencies in the fixed order `postgresql`, then
`active_model`. The response schema is version 1 and contains only stable
states and sanitized reason codes. It contains no timestamp, host, database
identity, path, credential, exception text or model prediction.

HTTP 200 is returned only when every dependency is ready. Any unavailable,
incompatible or unexpectedly failing required dependency produces HTTP 503 and
aggregate status `not_ready`.

The PostgreSQL probe explicitly maps development to the development target and
test to the test target. Production fails closed because no production target
is configured; it never falls back to development. A successful probe requires
the existing PostgreSQL version, UTC, restricted-role and connection-identity
checks plus exact Alembic head `f0009_step_7_9`. Its lazy engine is disposed
after every result.

The active-model probe delegates to the complete Step 7.1 resolver. It requires
exactly one explicitly active registry history and the full compatible
registry-to-runtime artifact chain. `development_accepted` is not active. The
actual registry therefore reports `no_active_model` and the application remains
not ready even while PostgreSQL is healthy.

No provider is a Step 8.1 runtime dependency because no provider-backed API
operation exists. No provider is selected or contacted. Historical raw-manifest
verification remains the mandatory pre-write repository gate; read-only health
checks neither replace nor weaken it.

## Request IDs

Every HTTP response carries `X-Request-ID`. A caller may supply one ASCII value
matching `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; the value is preserved exactly. A
missing ID receives a canonical UUID. Duplicate or invalid values are rejected
with HTTP 400 and a new safe UUID, so attacker-controlled data is not reflected
as the response identifier.

The current ID is available through a context-local accessor while request code
runs and is reset afterward. Request IDs are transport correlation data only;
they are not domain identities, provenance checksums or persistence keys.

## Error envelopes

All routing, method, validation, intentional API and unexpected application
errors use this versioned shape:

```json
{
  "schema_version": 1,
  "error": {
    "code": "not_found",
    "message": "Resource not found.",
    "request_id": "caller-or-generated-id",
    "details": []
  }
}
```

Validation details contain only location, stable type code and safe message.
Rejected input values, URLs, credentials, raw exception text and tracebacks are
never serialized. Unexpected failures return the generic code
`internal_server_error` and HTTP 500.

Step 8.2 does not add domain-specific error codes for endpoints that do not yet
exist. Later endpoint steps may raise the typed `ApiError` boundary without
changing the envelope.

## Pagination

Future collection endpoints share immutable offset contracts:

- default limit 50, maximum limit 100 and minimum limit 1;
- non-negative offset and total;
- ordered item tuples;
- returned count plus deterministic next and previous offsets; and
- fail-closed validation of item counts and metadata arithmetic.

No paginated endpoint is introduced in Step 8.2. Query semantics and ordering
for teams and seasons begin in Step 8.3.
