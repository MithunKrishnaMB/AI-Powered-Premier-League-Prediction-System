# Architectural Decision Register

These decisions describe implemented behavior and constraints as of the
Milestones A and B closeout. A later milestone may supersede a decision only by
recording the replacement and its migration impact.

## ADR-001 — Backend-first typed Python package

**Status:** Accepted  
**Context:** The platform will contain ingestion, feature engineering, machine
learning, simulation, persistence, an API, and eventually a frontend.  
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
GitHub Actions, CI/CD pipelines, or deployment automation.  
**Consequences:** The code retains engineering checks without adding operational
complexity. Running the checks is a local milestone responsibility rather than
an automatically enforced remote gate.

## ADR-003 — Manifest-pinned immutable raw data

**Status:** Accepted  
**Context:** A source URL can return different bytes over time, which would make
model training irreproducible.  
**Decision:** Track source URL, allowed hosts, capture time, encoding, required
shape, byte count, row count, and SHA-256 in a validated manifest. Store raw CSVs
outside Git, publish them without overwrite, and reject checksum conflicts.  
**Consequences:** A training input is byte-identifiable and reproducible. Source
corrections require an explicit manifest review rather than a silent overwrite.

## ADR-004 — Separate source, canonical, and quality boundaries

**Status:** Accepted  
**Context:** Provider column names and aliases should not leak into feature or
model code, and valid individual rows can still form an invalid season.  
**Decision:** Keep three boundaries: typed Football-Data records, provider-neutral
domain records, and cross-record competition validation. Resolve teams through
reviewed source aliases and stable UUIDs; do not use fuzzy matching.  
**Consequences:** Provider changes are isolated, domain code gets stable
identities, and failures have clearer ownership. More models and validation code
are required than in a single permissive dataframe pipeline.

## ADR-005 — Deterministic canonical identity and materialization

**Status:** Accepted  
**Context:** Re-running ingestion must not create new fixture identities or
different bytes for equivalent data.  
**Decision:** Generate fixture UUIDv5 values from competition, season, home team,
and away team. Sort by kickoff and fixture ID, serialize JSON with stable key
ordering, hash the output, and write a companion lineage manifest atomically.  
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
