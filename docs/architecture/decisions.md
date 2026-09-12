# Architectural Decision Register

These decisions describe implemented behavior through the completed Milestone C.
A later decision may supersede an accepted decision only by recording the
replacement and its migration impact.

## ADR-001 — Backend-first typed Python package

**Status:** Accepted  
**Context:** The platform will contain ingestion, feature engineering, machine
learning, simulation, persistence, an API and eventually a frontend.  
**Decision:** Use an installable `src/`-layout package on 64-bit Python 3.14.7.
Use Pydantic models at external and domain boundaries, strict mypy, Ruff, pytest,
and branch coverage with a 90% minimum.  
**Consequences:** Packaging mistakes and invalid boundary data fail early. The
narrow Python support window improves consistency but may limit compatibility
with libraries that have not yet released Python 3.14 wheels.

## ADR-002 — Local quality gates; no CI/CD

**Status:** Accepted user constraint  
**Context:** The user does not want DevOps or YAML-based automation in the
project.  
**Decision:** Keep deterministic local quality commands but do not configure
GitHub Actions, CI/CD pipelines or deployment automation.  
**Consequences:** The code retains engineering checks without adding operational
complexity. Running the checks is a local milestone responsibility rather than
an automatically enforced remote gate.

## ADR-003 — Manifest-pinned immutable raw data

**Status:** Accepted  
**Context:** A source URL can return different bytes over time, which would make
model training irreproducible.  
**Decision:** Track source URL, allowed hosts, capture time, encoding, required
shape, byte count, row count and SHA-256 in a validated manifest. Store raw CSVs
outside Git, publish them without overwrite and reject checksum conflicts.  
**Consequences:** A training input is byte-identifiable and reproducible. Source
corrections require an explicit manifest review rather than a silent overwrite.

## ADR-004 — Separate source, canonical and quality boundaries

**Status:** Accepted  
**Context:** Provider column names and aliases should not leak into feature or
model code and valid individual rows can still form an invalid season.  
**Decision:** Keep three boundaries: typed Football-Data records, provider-neutral
domain records and cross-record competition validation. Resolve teams through
reviewed source aliases and stable UUIDs; do not use fuzzy matching.  
**Consequences:** Provider changes are isolated, domain code gets stable
identities and failures have clearer ownership. More models and validation code
are required than in a single permissive dataframe pipeline.

## ADR-005 — Deterministic canonical identity and materialization

**Status:** Accepted  
**Context:** Re-running ingestion must not create new fixture identities or
different bytes for equivalent data.  
**Decision:** Generate fixture UUIDv5 values from competition, season, home team,
and away team. Sort by kickoff and fixture ID, serialize JSON with stable key
ordering, hash the output and write a companion lineage manifest atomically.  
**Consequences:** Rebuilds are idempotent and auditable. The identity scheme is
appropriate for one ordered home/away pairing per league season; cup or replay
fixtures will require an additional identity component.

## ADR-006 — Preserve missing kickoff precision

**Status:** Accepted  
**Context:** Football-Data seasons 2015–16 through 2018–19 provide match dates but
not kickoff times. Inventing a precise time could cause false temporal ordering
and feature leakage.  
**Decision:** Store UTC timestamps, interpreting known times in
`Europe/London`. For date-only rows, use local noon solely as a deterministic
anchor and set `kickoff_precision=date_only`. Future feature state must be
calculated before and updated after the complete same-date batch.  
**Consequences:** Older history remains usable without pretending the source is
more precise than it is. Feature engineering must explicitly support batch
semantics.

## ADR-007 — Canonical JSON Lines before analytical storage

**Status:** Accepted for Milestone B  
**Context:** The first durable derived format should be inspectable, hashable,
and independent of a database or dataframe library.  
**Decision:** Materialize one deterministic JSON object per fixture plus a
per-season dataset manifest under ignored `data/interim/`.  
**Consequences:** Canonical records are easy to inspect and reproduce. JSON Lines
is not the most compact analytical format; a later feature milestone may add a
columnar processed format without replacing the canonical source of truth.

## ADR-008 — Versioned point-in-time feature-row boundary

**Status:** Accepted

**Context:** Model inputs must remain traceable to verified canonical data and
post-match targets or falsely precise historical kickoff ordering must not enter
pre-match predictors.

**Decision:** Represent each feature example with an immutable, provider-neutral
schema containing canonical fixture, season and team identities; UTC kickoff
and feature-cutoff boundaries; a separately versioned predictor collection; an
optional nested training label; and checksum-pinned canonical, historical and
raw-source lineage. Derive a deterministic UUIDv5 row ID from the semantic row
and input lineage. For date-only fixtures, require the cutoff to precede the fixture's
`Europe/London` calendar date; chronological processing updates state only after
the complete same-date batch. Predictor representability does not grant
eligibility and retained bookmaker columns remain unapproved.

**Consequences:** Predictors and targets cannot be conflated accidentally by the
wire structure, equivalent inputs have stable identities and every row can be
traced to a manifest-verified source artifact. Feature definitions and material
calculations remain separate versioned responsibilities.

## ADR-009 — Pre-batch within-season rolling state

**Status:** Accepted; cross-season portion superseded by ADR-012 for predictor
schema version 2

**Context:** Historical sources may omit kickoff times, optional statistics may
be missing and early-season teams do not have comparable Premier League history
in the current season.

**Decision:** Reset version 1 feature state at each season boundary and use a
five-match form window alongside season-to-date aggregates. Snapshot all team
state before each chronological batch and commit fixture observations only after
every row in that batch has been created. If any fixture on a Premier League
calendar date in `Europe/London` is date-only, batch the whole local date. Retain
missing optional statistics as null averages with explicit observation counts.
Derive promoted status only from the
reviewed season registry, rest and congestion from prior fixture dates and
season progress from prior processed fixtures and known membership size.

**Consequences:** Current results cannot affect current predictors, unknown
within-day ordering cannot leak and missing statistics are distinguishable
from observed zeros. Version 1 deliberately has no cross-season carryover;
ADR-012 introduces reviewed, explicitly separate carryover in predictor schema
version 2 without changing factual within-season observation counts.

## ADR-010 — Deterministic processed feature artifacts

**Status:** Accepted

**Context:** In-memory feature rows are insufficient for reproducible training;
the persisted bytes must remain tied to the exact verified raw and canonical
inputs, feature schema and temporal semantics.

**Decision:** Materialize one compact, key-sorted JSON object per feature row
under ignored `data/processed/`, ordered by cutoff, kickoff and deterministic
row UUID. Publish an adjacent deterministic manifest containing output checksum
and count, all feature-related schema versions, the complete ordered predictor
schema and checksum, processing parameters, recursive historical-context
checksum, canonical fixture checksum and registry versions and raw source
checksum and capture identity. Invoke the existing checksum-verifying canonical
materializer for every required predecessor before building a target season,
validate canonical bytes against their manifests and publish files through
atomic replacement.

**Consequences:** Training inputs are byte-identifiable, stale generated outputs
are replaced without partial files and unchanged builds return
`already_current`. The JSON Lines representation is intentionally inspectable;
a later columnar representation must retain the same lineage and deterministic
semantics rather than silently replacing them.

## ADR-011 — Reproducible model-ready training dataset

**Status:** Accepted

**Context:** Reproducible feature files still need a single validated,
model-ready boundary. Combining seasons without pinning each input manifest or
without keeping post-match outcomes separate would allow provenance drift or
target leakage before model development begins.

**Decision:** Project every labeled feature row into immutable `TrainingExample`
schema version 1, retaining its point-in-time predictors and placing the result
and score only in a separate required `target`. Combine all manifest-listed
seasons in deterministic kickoff/UUID order. Bind each example to its source
feature row and season-specific feature dataset. Publish JSON Lines with a
versioned manifest that pins the training checksum, predictor and target
schemas, tracked input-file checksums and every feature, canonical and raw
source checksum plus each historical-context checksum. Re-run the raw-verifying
canonical and feature materializers before every combined build. Do not select a
temporal split or fit a model in this step.

**Consequences:** The first model-ready corpus is byte-reproducible and rejects
unknown or cross-season lineage, modified source artifacts, incomplete targets,
and predictor drift. Later model milestones must choose chronological training
and evaluation windows explicitly rather than treating this combined historical
corpus as a randomly splittable dataset.

## ADR-012 — Explicit season-opening priors

**Status:** Accepted

**Context:** Pure within-season aggregates are empty at kickoff of a season and
unstable during its first matches. Silently pooling future matches, unverified
lower-division data or pseudo-observations into factual counts would create
leakage or misleading denominators.

**Decision:** Predictor schema version 2 adds a separate opening-prior contract.
A continuing club uses its own immediately preceding Premier League result and
goal aggregates. A promoted club uses that preceding league's aggregate because
Championship results are not present in the verified dataset. Every club in the
first tracked season uses a fixed neutral prior: equal win/draw/loss rates, 4/3
points per match and 1.5 goals for and against. Blend the prior with observed
current-season results using a fixed five-match pseudo-weight, while leaving all
factual match and statistic counts unchanged. Expose the prior source through
mutually exclusive predictor flags and record every constant and source policy
in the feature manifest.

**Consequences:** Opening fixtures have finite, explicit form estimates without
using future information or pretending that pseudo-matches occurred. Promoted
clubs receive a deliberately coarse league fallback; introducing verified
Championship history would require a new prior schema and provenance chain.

## ADR-013 — Batch-safe cross-season Elo

**Status:** Accepted

**Context:** Elo supplies a compact strength estimate, but it can leak when one
fixture on an uncertain date updates a rating used by another fixture in the
same batch. Offseason and promoted-team initialization must also be explicit.

**Decision:** Elo schema version 1 starts at 1500, adds 65 rating points for home
advantage, uses K-factor 20 and a 400-point logistic scale and retains 75% of a
continuing club's deviation from 1500 between seasons. Promoted clubs and every
club in the first tracked season initialize at 1500. Calculate all expected
scores and result deltas from one pre-batch rating snapshot, then apply the
accumulated zero-sum deltas after the batch. Persist ratings and expected scores
only as pre-match predictors. Bind cross-season state to a recursive checksum of
all preceding verified canonical and raw inputs plus the parameter policy.

**Consequences:** Exact and date-only fixtures share the same leakage boundary,
reruns produce identical rating histories and changed predecessor data changes
downstream row identities. Elo expected score remains a benchmark signal rather
than a calibrated three-outcome probability model.
