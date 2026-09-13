# Simulation Domain, Scorelines and Table Rules

## Scope

Milestone E Steps 4.4 through 4.6 define the typed input and state contracts for
one season simulation, deterministic sampling from an explicit scoreline
distribution and immutable Premier League table updates and ranking. They do
not generate score distributions, execute or vectorize a complete simulation,
aggregate simulation results or persist outputs.

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

## Deferred work

Step 4.7 will execute and vectorize 10,000 simulations from these contracts.
Step 4.8 will define aggregate threshold and position probabilities and Step
4.9 will add whole-simulator invariants and reproducibility tests. Those steps
must resolve how externally approved scoreline distributions enter the run and
how a statistically unresolved official playoff is represented before complete
position probabilities can be claimed.
