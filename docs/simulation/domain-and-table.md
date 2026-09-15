# Simulation Domain, Scorelines and Table Rules

## Scope

Milestone E Steps 4.4 through 4.9 define the typed input and state contracts for
season simulation, deterministic sampling from an explicit scoreline
distribution, immutable Premier League table updates, fixed 10,000-run
vectorized execution, aggregate probabilities and reproducibility invariants.
They do not generate score distributions or persist outputs.

The development-accepted CatBoost artifact emits three-way outcome
probabilities only. It is not a score model. The simulator therefore requires a
separate `FixtureScorelineDistribution` for every remaining fixture and never
converts home-win, draw and away-win probabilities into invented scorelines.
The producer and approval of those distributions remain a later integration
decision.

## Domain contracts

Simulation schema version 1 provides frozen, strict Pydantic contracts for:

- scorelines bounded to 0 through 40 goals for each team;
- positive, canonically ordered scoreline probability entries whose mass sums
  to one within `1e-12`;
- content-derived UUIDv5 distribution identities bound to the canonical fixture
  and team UUIDs and the exact ordered probability values;
- remaining fixtures with UTC kickoff time and explicit kickoff precision;
- completed or sampled fixture results;
- sampled-result UUIDv5 identities bound to the distribution, seed, simulation
  index and scoreline;
- canonical 20-team season input; and
- immutable table, ranked-row and ranked-table structures.

Team membership uses canonical UUIDs only. The contracts contain no provider
name resolution and perform no fuzzy matching. Completed fixture IDs and
remaining fixture IDs must be unique and disjoint.

The existing point-in-time chronology boundary is preserved. If any fixture on
a Premier League calendar date has `date_only` precision, every fixture on that
date is one simultaneous batch ordered only by fixture UUID. On dates containing
only exact timestamps, identical kickoffs form a batch. Steps 4.4–4.6 consume
already-prepared distributions and do not update predictors between fixtures.

## Deterministic sampling

Sampling is stateless. For each `(simulation seed, simulation index, fixture
UUID)`, the sampler hashes the UTF-8 identity with SHA-256, reads the first
unsigned 64 bits in big-endian order and divides by `2^64` to obtain a value in
`[0, 1)`. Canonical inverse-CDF selection then chooses a scoreline.

The seed must be an unsigned 64-bit integer and the simulation index must be a
non-negative integer. Because the fixture UUID is part of the draw identity,
iterating fixtures in a different order cannot change their sampled results.
The probability order and the final rounding-tail fallback are explicit.

## Table updates and ranking

The table engine stores a canonical fixture ledger and rebuilds immutable rows
from it. Each result updates both teams' played, won, drawn, lost, goals for,
goals against and points values. Wins award three points, draws one and losses
zero. Duplicate fixture application, non-member teams and row/ledger mismatch
fail closed.

Final ranking follows the Premier League order documented in Rule C.17: points,
goal difference, goals scored, points in matches between the tied clubs and
away goals in those head-to-head matches. See the Premier League's
[2025/26 explanation of the rule](https://www.premierleague.com/en/news/4638196/could-the-premier-league-title-be-won-on-goal-difference).

If all five statistical criteria remain tied, the rules require a neutral-venue
playoff when a material placing must be decided. This implementation raises
`UnresolvedTableTieError`. It does not use club names, alphabetical order or
canonical UUIDs as a hidden sporting tiebreak and does not simulate a playoff.

## Vectorized execution

`simulate_season_10k` always executes exactly 10,000 runs. It derives the same
stateless fixture draws defined above, performs inverse-CDF selection in NumPy
and accumulates points, goals for and goals against across the run axis. Result
matrices are read-only and use `int64` for table totals, `int16` for sampled
goals and float64 for position mass.

The simulation UUID binds schema and algorithm version, the full completed
fixture ledger, ordered remaining fixture and distribution identities, canonical
team order, season, unsigned 64-bit seed and fixed run count. Repeating an
unchanged input and seed returns byte-identical matrix values and the same UUID.

Primary ranking is vectorized across points, goal difference and goals scored.
Head-to-head points and away goals are evaluated only for primary tie groups.
When official statistics still require a playoff, each tied team receives equal
fractional probability over the unresolved occupied positions. This preserves
unit probability for every team and every position without claiming which club
would win an unplayed playoff. The strict single-table API continues to raise
`UnresolvedTableTieError` when a unique official order is requested.

## Aggregation and invariants

`aggregate_simulations` emits expected points, goals for, goals against and goal
difference plus all 20 finishing-position probabilities for each team. It also
derives champion, top-four, top-six and relegation probabilities. The aggregate
summary UUID binds the run and exact team summaries.

Validation requires every team's position probabilities to sum to one, every
position's probability across teams to sum to one and league-wide champion,
top-four, top-six and relegation mass to total one, four, six and three. Tests
also verify exact repeated-run equality, order-independent fixture draws,
score-distribution frequencies, goals-for/goals-against conservation, points
bounds, immutable arrays and summary identity rejection after tampering.

## Deferred work

Step 5.1 has finalized the future persistence shape in the
[PostgreSQL entity-relationship model](../architecture/postgresql-entity-relationship-model.md).
It does not serialize simulation outputs or configure a database.

Scoreline distribution content and producer provenance are separate immutable
entities. This preserves a distribution's existing content-derived UUID while
allowing independently traceable provenance attestations. Every persisted
remaining fixture must select both a distribution and one provenance record.
The current CatBoost artifact cannot be a producer because its prediction
contract explicitly denies scoreline capability.

A persisted simulation input preserves explicit team, completed-fixture,
remaining-fixture, distribution and simultaneous-batch order. Its run keeps the
existing deterministic UUID, unsigned 64-bit seed, algorithm version 1 and
exactly 10,000 simulations. Future result components must retain their exact
bytes, shapes and `int64`, `int16` or `float64` dtypes. Aggregate summaries use
their existing UUID and normalized team and 20-position rows with deferred
league-wide mass constraints.

Step 7.7 now accepts already supplied scoreline distributions only through an
explicit immutable approval record containing producer identity/version, exact
input checksum, runtime contract, numerical contract and approval context. It
uses the advanced official-result ledger to rebuild and persist the canonical
10,000-run input, six exact NumPy result components and aggregate summary while
retaining the prior run as supersession lineage. It does not select a provider
or score model. The registered CatBoost artifact remains insufficient and is
never converted from three-way probabilities into scoreline mass.
