# Frontend Application Architecture

## Scope

Milestone L Step 11.1 fixes the frontend architecture before any frontend
project, package manifest, dependency, generated client or hosted resource
exists. It reassesses the planned Next.js boundary against the completed
FastAPI release and records the constraints that Step 11.2 and later frontend
steps must follow.

This step adds documentation only. It does not initialize Next.js or
TypeScript, select or install a package, generate an OpenAPI client, add a
lockfile, create a frontend environment file, change CORS, deploy a service or
modify the backend.

## Reassessment result

Use a separate Next.js 16 App Router application under `frontend/`. The App
Router remains a good fit because layouts, pages and backend reads can default
to Server Components, while the small number of genuinely interactive controls
can remain isolated Client Components. A client-only single-page application
would move the complete transport and data-loading boundary into the browser,
require production CORS changes immediately and send more JavaScript than this
read-mostly application needs. A static Next.js export would also prevent the
planned dynamic resource routes without enumerating production identities at
build time.

The frontend is a presentation and navigation layer over the existing public,
GET-only API. It does not gain database access, import Python code, load model
artifacts, call a current-data provider or execute prediction or simulation
workflows.

## Repository, runtime and package boundary

Step 11.2 must create exactly one JavaScript package below `frontend/`. The
repository root remains the Python project and does not become a JavaScript
workspace. Frontend source, configuration, tests, the OpenAPI snapshot and
generated client all remain below that directory.

Use 64-bit Node.js 24.21.0 LTS with npm 11.19.0. Record the exact runtime and
package-manager versions in the frontend package and a version-manager file.
Commit `package-lock.json` and use `npm ci` for clean verification and
deployment installs. Direct dependencies and development dependencies use exact
versions without caret, tilde or `latest` ranges. Do not introduce npm
workspaces, an alternative package manager or a second lockfile.

The Python 3.14.7 package, `pyproject.toml`, backend dependency pins and local
release command remain unchanged.

## TypeScript boundary

Step 11.2 must use TypeScript for all application and test source. In addition
to the Next.js-required compiler settings, enable:

- `strict`;
- `noUncheckedIndexedAccess`;
- `exactOptionalPropertyTypes`;
- `noImplicitOverride`;
- `noFallthroughCasesInSwitch`;
- `noPropertyAccessFromIndexSignature`;
- `useUnknownInCatchVariables`;
- `forceConsistentCasingInFileNames`; and
- `noEmit` for the explicit type-check command.

Do not weaken a strict option to accommodate generated code. Generated output
must compile under the same project configuration and any generator
incompatibility must be resolved at the generator configuration or dependency
version boundary.

## Deterministic OpenAPI client

The FastAPI application factory and its OpenAPI 3.1 document are the only
contract source. The frontend must not maintain handwritten copies of endpoint,
parameter, pagination, resource or error-envelope types.

Step 11.2 must implement this ordered generation path:

1. Construct the local FastAPI application with explicit deterministic
   settings and export `app.openapi()` without starting Uvicorn, opening a
   database connection or contacting Render.
2. Serialize the complete document as canonical, key-sorted JSON with one final
   newline below `frontend/openapi/`.
3. Generate immutable, alphabetized TypeScript path and component types with an
   exactly pinned `openapi-typescript` release.
4. Use an exactly pinned `openapi-fetch` client behind one application-owned,
   server-only transport adapter.
5. Commit both the OpenAPI input snapshot and generated TypeScript output.
6. Provide separate generation and drift-check commands. The drift check must
   regenerate from the local backend and fail when either tracked artifact
   changes.

Generation must never depend on the public Render endpoint, network timing or
an unpinned `npx` download. Generated files are not edited manually. Application
view models may derive presentation values from generated types but must not
rename the snake-case wire contract or redefine it independently.

The current input contract is exactly sixteen GET operations: two health
operations and fourteen `/api/v1` resource operations. Any later backend path,
method, operation-ID or schema change must first pass the existing backend
OpenAPI contract tests and then intentionally regenerate the frontend artifacts.

## Rendering and component ownership

Pages, layouts, metadata, data loading, API error classification and initial
rendering are Server Component responsibilities. Client Components are narrow
interaction islands only where browser state or an event handler is required,
including responsive navigation, filter controls, accessible visualization,
copying a request ID and delayed cold-start messaging.

Do not mark a route layout or complete page as a Client Component merely to
support one interactive descendant. Do not call the backend from Client
Components. Server Components call the generated client through the one
server-only adapter and pass serializable presentation data downward.

Use App Router route segments for durable resource identity. Use URL search
parameters for season, team, fixture status, simulation selection, `limit` and
`offset`. A copied or refreshed URL must reproduce the same view. Local
component state is limited to ephemeral interaction such as an open menu or
selected visualization tab. Do not add a global client state store or treat
browser storage as authoritative application state.

## Data fetching and caching

Every backend resource response currently carries `Cache-Control: no-store`.
Frontend backend calls must therefore use `cache: "no-store"` and must not add
ISR, timed revalidation, tag revalidation or a second persistent data cache.
Deduplication within one render is acceptable, but data must not be retained
across requests as an application cache.

Disable speculative prefetch for backend-backed navigation so a visible link
does not wake the free backend or consume its process-local request quota. Do
not add background polling, automatic retries, a service worker, keep-alive
traffic or a client query-cache dependency. A user action may explicitly retry
or refresh a view.

The aggregate readiness endpoint is an operational summary, not a gate in
front of every resource page. Its intentional HTTP 503 with PostgreSQL `ready`
and active model `no_active_model` means forecast products are unavailable; it
does not by itself prove that an independent persisted resource read will fail.

## Pagination

Collection routes preserve the backend's offset contract. The frontend exposes
page sizes 25, 50 and 100, defaults to 50 and stores the selected `limit` and
current `offset` in the URL. Filters reset `offset` to zero.

Next and previous controls use the returned `next_offset` and
`previous_offset`; they do not duplicate the backend arithmetic. Displayed
counts use `returned` and `total`. The frontend does not re-sort a page or imply
that client-side order replaces the API's deterministic canonical ordering.
Invalid URL pagination values produce a local recovery view with a link to the
canonical first page rather than sending an avoidable invalid request.

## Request IDs and errors

Every backend call sends one valid `X-Request-ID`. An incoming valid correlation
value may be propagated; otherwise the frontend generates a UUID. The adapter
requires the returned `X-Request-ID` and, for an error envelope, requires the
header and `error.request_id` to agree. Missing or conflicting identifiers are
treated as a backend contract failure rather than silently replaced.

The adapter maps transport failures and the uniform 400, 403, 404, 422, 429,
500 and resource-503 envelopes into one discriminated frontend error type. It
also handles the readiness-specific 503 response separately because that body
is `ReadinessResponse`, not `ErrorEnvelope`. UI code receives only the safe
message, stable code, status, safe details, retry interval when present and
request ID. It must not display raw exception text, URLs, stack traces or
rejected values.

Use resource-specific not-found pages for known 404 codes. Treat 422 caused by
URL state as a recoverable invalid-filter state. Respect `Retry-After` on 429
without scheduling an automatic retry. Unexpected, unavailable and contract
failures show a manual retry and the request ID for support.

## Loading, empty, unavailable and cold-start states

Every backend-backed route must define all of these states before its success
view is considered complete:

- **Loading:** render a stable, low-motion skeleton through `loading.tsx`, keep
  headings and page geometry recognizable and mark the result region busy.
- **Empty:** render an HTTP-success state that explains no persisted rows exist.
  Never offer to generate a prediction, scoreline distribution or simulation.
- **Not found:** explain that the requested persisted identity is absent and
  provide a safe collection route.
- **Error:** show the sanitized message, request ID and one explicit retry.
- **Unavailable:** distinguish database/network failure and rate limiting from
  an empty successful collection.
- **Forecast unavailable:** explain that no active model exists when predictions
  or simulations are absent for that reason. Do not call
  `development_accepted` active.
- **Cold start:** show the normal loading state immediately, add a quiet
  free-tier wake-up explanation after five seconds and rely on a user retry if
  the host or request deadline fails. Do not generate keep-alive traffic or
  repeated wake-up requests.

Empty prediction and simulation collections are first-class current production
states. The interface must not fabricate sample forecasts, relabel development
metrics as live performance or mask absence with a generic error.

## Styling and component system

Use global CSS only for reset, typography, colour tokens and page-level
foundations. Use CSS Modules for component styles and CSS custom properties for
spacing, type, colour, elevation, focus and motion tokens. Prefer semantic HTML
and native controls before creating a custom primitive.

Keep reusable primitives below a UI component boundary and domain compositions
within their feature. A primitive must not import the API client or a football
feature. Feature components may compose primitives and generated API types
through presentation adapters. Do not add Tailwind, CSS-in-JS, a UI kit, a
component generator or a charting dependency during architecture or
initialization. A later visualization dependency requires a separately reviewed
need and an accessible tabular equivalent.

## Accessibility and responsive behavior

Target WCAG 2.2 AA. Every page must have a unique title, one primary heading,
landmarks and a keyboard-reachable skip link. Focus indicators remain visible,
route changes move focus predictably, controls have programmatic names and
status changes use restrained live-region announcements. Probability meaning
must never depend on colour alone and reduced-motion preference must be
honoured.

Tables keep captions and header associations. On narrow screens they may use a
labelled horizontal scroll region or a semantic card projection, but no field
may disappear merely to fit the viewport. Layouts begin as one column, add
columns only when content permits and must not create page-level horizontal
scroll. Interactive targets meet the WCAG 2.2 AA minimum target size.

Support the unmodified Next.js baseline of Chrome 111+, Edge 111+, Firefox 111+
and Safari 16.4+. Step 11.10 must exercise Chromium, Firefox and WebKit rather
than claiming support from Chromium alone.

## Testing layers and local quality commands

Later implementation uses these layers:

1. TypeScript compilation and ESLint for all source and generated contracts.
2. Deterministic OpenAPI export/generation drift checks.
3. Unit tests for URL state, formatters, error mapping, pagination and pure
   presentation adapters.
4. Component tests for semantic output, keyboard behavior, empty/error states
   and automated accessibility rules.
5. Fetch-boundary integration tests for success, empty, 404, 422, 429, 500,
   503, network timeout and request-ID mismatch responses.
6. Playwright end-to-end tests in Chromium, Firefox and WebKit using
   deterministic mocked API responses for normal local verification.
7. Separately authorized production smoke tests in Step 11.12.

No CI/CD workflow runs these commands. They remain explicit local milestone
checks. Live Render and Neon are not dependencies of the ordinary frontend test
suite.

## Public backend URL, CORS and environment handling

The frontend receives the publicly reachable backend origin through one
server-only, non-secret variable named `PLP_API_BASE_URL`. Do not prefix it
with `NEXT_PUBLIC_`; public reachability does not require browser ownership.
Local configuration belongs only in ignored `frontend/.env.local`. A tracked
example may contain a placeholder but no credential.

Validate the value before serving a backend-backed route. It must be one
absolute HTTP origin in local development and one absolute HTTPS origin in
production, with no username, password, path, query or fragment. Do not fall
back from production to a local URL.

Because the browser does not call Render, Step 11.1 and the planned frontend do
not require a CORS change. The backend's exact-origin allowlist remains empty
and Render retains its existing seven settings. A later proposal to introduce
direct browser API calls would require a separately reviewed CORS and
deployment change; it is not implied by this architecture.

## Zero-cost deployment boundary

Step 11.11 may create one manually released, Next.js-compatible Node service on
a zero-cost tier. It must run the reviewed build from an exact commit, use the
pinned Node/npm boundary, set only the server-side API origin and expose no
secret or database credential. Automatic deploys, preview environments,
persistent storage, databases, paid analytics, scheduled jobs and keep-alive
traffic remain prohibited.

The frontend is not a static export because dynamic resource identities and
request-time no-store reads are required. Free-tier frontend and backend cold
starts are accepted and represented honestly in the UI. Host selection,
provisioning and production environment changes remain Step 11.11; Step 11.1
creates none of them.

## Ordered page and feature map

The remaining Milestone L order is:

1. **Step 11.2 — foundation:** initialize the isolated package, strict
   TypeScript and local quality commands; export the local OpenAPI snapshot;
   generate the client; and implement only the server transport boundary.
2. **Step 11.3 — dashboard and navigation:** shared shell and `/`; service and
   forecast availability, season context and truthful empty production state.
3. **Step 11.4 — fixtures and predictions:** `/fixtures`,
   `/fixtures/[fixture_id]`, `/predictions` and
   `/predictions/[prediction_id]`, with filters and offset pagination.
4. **Step 11.5 — teams and squad availability:** `/teams` and
   `/teams/[team_id]`. The present API has no player or squad operation, so a
   squad view must state that the resource is unavailable. It must not query the
   database directly or expand the sixteen-operation API implicitly.
5. **Step 11.6 — standings:** `/standings` for the latest persisted actual
   snapshot and `/standings/predicted` selected by an existing simulation ID.
6. **Step 11.7 — simulations:** `/simulations` and
   `/simulations/[simulation_id]`, with accessible table-first position and
   threshold probability presentation.
7. **Step 11.8 — history and model evidence:** `/history`, `/models` and
   `/models/[model_id]/performance`, labelled strictly as persisted development
   evidence rather than final-test or production performance.
8. **Step 11.9 — near-live match centre:** `/match-centre`, limited to a manual
   refresh of persisted fixture state. It must disclose that no production
   provider is connected and must not add polling or claim live coverage.
9. **Step 11.10 — frontend verification:** accessibility, component,
   integration and cross-browser end-to-end coverage.
10. **Step 11.11 — deployment:** provision and manually deploy the single
    zero-cost frontend service under the boundary above.
11. **Step 11.12 — production integration:** exercise the deployed frontend and
    backend contract without creating model, provider or sealed-test evidence.

## Preserved backend and data boundaries

The frontend cannot change the sixteen-operation GET-only contract, PostgreSQL
isolation, production fail-closed behavior, active-model policy, registry,
artifact corpus, provider selection or sealed 2025–26 target. It consumes only
persisted read projections. Python imports and backend dependency construction
remain lazy and side-effect free. Neon and Render retain their current
zero-cost, manual deployment configuration.
