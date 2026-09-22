# Production Container Runtime

Milestone K Step 10.2 packages the existing read-only FastAPI backend for a
production-shaped process without deploying it or provisioning dependencies.
The boundary is locally buildable and testable, contains no credentials or
production artifacts and retains every fail-closed application contract.

## Reproducible image

The root `Dockerfile` uses the exact Python 3.14.7 slim-trixie image and pins its
multi-platform manifest digest. Project dependencies remain exact direct pins
in `pyproject.toml`; Uvicorn 0.53.0 is the only dependency added by this step.
The package is installed from the copied source rather than from an external
project release.

The `.dockerignore` file is deny-by-default. The build context admits only the
Dockerfile, ignore rules, README, project metadata and `src/` package. In
particular, it excludes Git metadata, environment files, tests, documentation,
local databases, raw data and every artifact corpus.

The image creates UID/GID 10001, gives that account ownership only of
`/runtime` and switches to `10001:10001` before startup. It does not create an
empty registry history: `/runtime/artifacts/registry` remains absent until a
separately authorized production artifact import supplies a valid corpus.

## Process boundary

The image entry point is:

```text
python -m pl_platform.api.production_runtime
```

That side-effect-free module validates that `PLP_ENVIRONMENT` is exactly
`production` before replacing itself with the pinned Uvicorn command. The ASGI
target remains the explicit `pl_platform.api:create_app` factory. It binds the
validated platform `PORT` when supplied and defaults to 8000 locally, runs
exactly one worker, disables generic proxy-header trust and access logging, and
allows 30 seconds for graceful shutdown.

One worker is deliberate. The existing bounded rate limiter is process-local;
multiple workers would silently create independent limits. Step 10.4 keeps
Uvicorn proxy forwarding disabled and trusts only Render's overwritten,
validated `CF-Connecting-IP` header inside the application. Generic forwarded
headers remain caller-controlled and untrusted.

Imports remain side-effect free. Importing the entry-point module neither reads
configuration nor starts a process; validation and process replacement occur
only from `main()`.

## Configuration and secrets

The image contains these non-secret defaults:

- `PLP_ENVIRONMENT=production`;
- `PLP_ARTIFACT_ROOT=/runtime/artifacts`; and
- `PLP_REGISTRY_ROOT=/runtime/artifacts/registry`.

Secrets are runtime inputs only. They must be supplied through an ignored local
environment file or a future deployment secret mechanism, never through the
Dockerfile, image layers, tracked files or command-line literals. This step
does not define a production database URL and does not copy the development or
test PostgreSQL settings into the image. Step 10.4 supplies only the pooled,
read-only `PLP_PRODUCTION_DATABASE_URL` through Render's runtime secret store;
the direct migration URL never reaches the image or service.

Overriding `PLP_ENVIRONMENT` to any non-production value terminates the entry
point before Uvicorn starts. When production database configuration is absent,
database selection continues to fail closed; there is no development or test
fallback.

## Health contract

The container healthcheck calls `GET /health/live`. Liveness proves only that
the process can serve HTTP and remains independent of PostgreSQL and model
state. It is therefore suitable for container process health.

`GET /health/ready` remains the dependency gate. With this intentionally empty
image it returns HTTP 503 with `production_database_not_configured` and
`no_active_model`. That is the expected state: the actual repository registry
still ends at `development_accepted`, no active model exists and no production
artifact corpus has been imported. A container must not be routed as ready
until later authorized work satisfies both dependencies.

The application still exposes exactly sixteen GET-only OpenAPI operations and
retains the existing request-ID, sanitized error, pagination, CORS, security-
header and rate-limit behavior. The healthcheck does not create predictions,
scoreline distributions or simulations.

## Deterministic local verification

Build and start the image locally:

```powershell
docker build --tag pl-platform-backend:local .
docker run --detach --rm `
  --name pl-platform-backend-local `
  --publish 127.0.0.1:8000:8000 `
  pl-platform-backend:local
```

Verify the two distinct health meanings:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-WebRequest `
  http://127.0.0.1:8000/health/ready `
  -SkipHttpErrorCheck
docker inspect `
  --format '{{.State.Health.Status}}|{{.Config.User}}' `
  pl-platform-backend-local
docker stop pl-platform-backend-local
```

The local contract tests also verify the base digest, allowlisted build context,
non-root runtime, production entry-point validation, one-worker Uvicorn command
and a real loopback Uvicorn process with the sixteen-operation API surface.

## Hosted continuation

Steps 10.3 and 10.4 select Neon Free and Render Free and implement their local
configuration and runbook. The Render Blueprint defines one manually deployed
Free Singapore service, uses `/health/live`, disables automatic deploys and
prompts for the pooled URL. External provisioning remains incomplete at the
provider sign-in boundary. No current-data provider, artifact import, sealed-
target inspection, registry mutation, prediction, automation or CI/CD is
introduced.
