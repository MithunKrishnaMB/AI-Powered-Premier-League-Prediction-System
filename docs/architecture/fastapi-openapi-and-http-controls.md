# FastAPI OpenAPI and HTTP Controls

## Scope

Steps 8.8 and 8.9 publish the already-reviewed read-only API contract and add
factory-scoped browser and HTTP controls. They introduce no new football
resource, workflow command, database write, provider integration, artifact load
or deployment configuration.

## OpenAPI contract

`GET /openapi.json` publishes OpenAPI 3.1 and `GET /docs` serves Swagger UI.
ReDoc remains disabled. Operation IDs are explicitly fixed for the two health
operations and fourteen `/api/v1` resource operations. The contract documents
the versioned response models and the shared 400, 403, 404, 422, 429, 500 and
503 error envelope. Readiness retains its typed 503 health response.

Contract tests pin the exact path-to-operation mapping, require unique operation
IDs, verify representative response and component schemas and prohibit POST,
PUT, PATCH and DELETE operations. Documentation publication does not add an
ASGI server, deployment entry point or mutable endpoint.

## CORS policy

Browser origins use an exact configured allowlist. The default list is empty,
so browser cross-origin access is denied. Wildcards, credentials embedded in an
origin, paths, queries, fragments and duplicate normalized origins are rejected
at settings validation. Host names are normalized case-insensitively while an
explicit scheme and port remain part of the identity.

Allowed preflights support only GET and OPTIONS and only `Accept`,
`Content-Type` and `X-Request-ID`. Preflight responses include a bounded max
age and complete `Vary` metadata. Credentials are disabled by default and may
be enabled only with explicit exact origins. A disallowed or malformed origin
uses the shared sanitized 400 or 403 envelope and never reflects the rejected
origin.

## Security headers

Every response, including generated errors and preflights, receives:

- `Cache-Control: no-store`;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- a restrictive permissions policy;
- `X-Permitted-Cross-Domain-Policies: none`; and
- a content security policy.

API responses use `default-src 'none'`. The `/docs` policy permits only the
specific CDN resources used by FastAPI's generated Swagger UI while retaining
blocked frames, base URIs and forms. HSTS is emitted only in the production
environment, where HTTPS termination is a deployment responsibility; local
HTTP development does not receive an HSTS policy.

## Rate controls

A factory-scoped sliding-window limiter defaults to 120 requests per 60 seconds
for each direct peer address. It does not trust forwarded-address headers.
Accepted and rejected requests receive deterministic `RateLimit-Limit`,
`RateLimit-Remaining` and `RateLimit-Reset` values; rejection returns HTTP 429,
`Retry-After` and the common `rate_limit_exceeded` envelope.

Liveness and CORS preflights are exempt. Readiness, OpenAPI, documentation and
resource reads are limited. Client state is process-local, lock-protected and
bounded to a configured maximum with least-recently-used eviction. This is a
single-process abuse guard, not a distributed quota service; deployment-scale
rate enforcement remains a future operational concern.

Step 10.4 keeps direct-peer identity as the default and adds one explicit
deployment exception. When `PLP_TRUSTED_CLIENT_IP_HEADER=CF-Connecting-IP`, a
single syntactically valid IPv4 or IPv6 value becomes the limiter key. Render's
edge overwrites this header, while caller-controlled `X-Forwarded-For` remains
untrusted and Uvicorn proxy-header handling remains disabled. Missing,
duplicate or malformed trusted-header values fall back to the direct peer. The
Render setting prevents all public users from sharing the load balancer's one
rate bucket without broadening trust in generic forwarding headers.

## Construction and preserved boundaries

Settings, limiter state and HTTP controls are constructed only by
`create_app`. Module import performs no settings load, timer read, connection,
registry inspection or artifact loading. The request-ID middleware remains the
outer contract: every response, including a CORS or rate rejection, carries a
validated or generated ID and the established security headers.

Development and test PostgreSQL isolation, exact migration-head reads and the
historical raw-manifest pre-write gate are unchanged. The sealed 2025–26 target
is not inspected. No model is activated, no prediction, scoreline, simulation
or metric is generated and the actual `development_accepted` registry state is
not mutated.
