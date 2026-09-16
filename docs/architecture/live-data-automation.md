# Live-Data Polling, Reconciliation and Job Commands

## Implemented boundary

Milestone J Steps 9.2 through 9.4 add provider-neutral orchestration around the
Step 9.1 exact-cache reader. They do not select a provider, run a scheduler or
change the FastAPI surface.

`KickoffAwarePollingPolicy` is a pure function over canonical current fixtures
and an explicit UTC evaluation time. It performs no sleeping, network access,
database access or registration with an external scheduler. Duplicate fixture
identities and non-UTC evaluation instants fail closed.

## Deterministic polling bands

The policy produces one ordered decision per canonical fixture and the earliest
pending time for the collection:

- in-progress fixtures: one minute;
- exact kickoffs already due: five minutes;
- exact kickoffs within six hours: fifteen minutes, clamped to kickoff;
- exact kickoffs from six to 48 hours: one hour;
- exact kickoffs from two through seven days: six hours;
- exact kickoffs more than seven days away: one day;
- postponed fixtures: six hours; and
- cancelled, abandoned or finished fixtures: no further fixture poll.

A date-only record never treats its noon storage anchor as a real kickoff.
Before the provider-local calendar date it is checked at most daily and is
clamped to local midnight; during that local day it is checked hourly; after
the day it is checked every six hours until official reconciliation changes
its state.

`FixturePollingJob` composes the Step 9.1 reader, immutable fixture
synchronization and this policy. It persists only a complete non-empty page
collection and computes the next policy result after synchronization. It still
does not schedule the returned time.

## Final-match reconciliation

`CacheAwareFinalResultReconciler` applies the same exact-request cache states as
fixture reads to the existing `completed_results` capability. Fresh compatible
bytes are decoded without provider contact. Stale or missing entries require an
injected provider whose complete compatibility manifest declares the
capability supported. Incompatible evidence, absent providers and unsupported
or temporarily unavailable capabilities fail with stable sanitized categories.

All pages must finish before any write. Cursor cycles and duplicate provider or
canonical fixture identities fail before persistence. Completed results are
mapped only through reviewed team resolution and canonical fixture UUIDs, then
the complete non-empty set is passed once to `CurrentSeasonRepository`. The
existing raw-manifest gate, prior-fixture requirement, immutable official-score
ledger, retrieval-time knowledge boundary and idempotent conflict checks remain
authoritative. An empty complete response is a deterministic no-op.

## Safe command boundary

The `plp-current-data` executable exposes two commands:

```text
plp-current-data poll-fixtures --target development --season-id 2026-2027 --at 2026-09-16T10:00:00Z
plp-current-data reconcile-final-matches --target test --season-id 2026-2027 --at 2026-09-16T10:00:00Z
```

Only `development` and `test` are accepted. Season syntax and an explicit UTC
evaluation instant are mandatory. Output is canonical compact JSON and errors
contain only stable non-secret information. The installed default runner fails
closed because no production provider or current-data runtime composition has
been approved; tests inject the provider-neutral job runner explicitly. Module
import constructs no engine, provider client, model or artifact.

These commands are execution boundaries, not scheduling configuration. No
GitHub Actions, CI/CD, cron substitute, credential setting, production target,
prediction, simulation, registry transition or model monitoring is included.
The separately implemented Step 9.5 retraining workflow is not invoked by
these commands and has no scheduling integration.
