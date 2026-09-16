# Architecture Documentation

This directory holds implementation-aligned architecture records for the
Premier League prediction platform.

Planned topics include:

- system context and component boundaries
- canonical football data and team identity
- point-in-time feature generation and leakage prevention
- model training, validation, calibration and versioning
- score modelling and season simulation
- PostgreSQL schema and migration strategy
- provider adapters, caching and ingestion workflows
- FastAPI contracts and scheduled jobs
- deployment and operational decisions
- frontend architecture, after backend acceptance

Major decisions will record the decision, alternatives, rationale and
trade-offs. Documentation should describe implemented behavior rather than
speculative future complexity.

## Current records

- [Architectural decision register](decisions.md)
- [Current-provider capability and domain contracts](../data/current-provider-contracts.md)
- [Current-provider transformations, transport and caching](../data/current-provider-integration.md)
- [Current-season fixture, result and standings synchronization](../data/current-season-synchronization.md)
- [Current players, squads and recorded-response contracts](../data/current-squads-and-recorded-contracts.md)
- [PostgreSQL entity-relationship model](postgresql-entity-relationship-model.md)
- [PostgreSQL connections and Alembic boundary](postgresql-connections-and-alembic.md)
- [PostgreSQL migration chain](postgresql-migrations.md)
- [PostgreSQL repositories and transactions](postgresql-repositories.md)
- [FastAPI application and transport boundary](fastapi-application-and-transport.md)
- [Point-in-time feature processing](../features/point-in-time.md)
- [Probabilistic development evaluation](../models/probabilistic-evaluation.md)
- [Simulation domain, scorelines and table rules](../simulation/domain-and-table.md)
- [Implementation roadmap](../roadmap.md)
- [Project status](../project-status.md)
- [Milestone B to C handoff](../handoffs/milestone-b-to-c.md)
- [Milestone C to D handoff](../handoffs/milestone-c-to-d.md)
- [Milestone D to E handoff](../handoffs/milestone-d-to-e.md)
- [Milestone E to F handoff](../handoffs/milestone-e-to-f.md)
- [Step 5.1 to 5.2 handoff](../handoffs/step-5-1-to-5-2.md)
- [Step 5.3 to 5.4 handoff](../handoffs/step-5-3-to-5-4.md)
- [Step 5.7 to 5.8 handoff](../handoffs/step-5-7-to-5-8.md)
- [Milestone F to G handoff](../handoffs/milestone-f-to-g.md)
- [Step 6.4 to 6.5 handoff](../handoffs/step-6-4-to-6-5.md)
- [Step 6.7 to 6.8 handoff](../handoffs/step-6-7-to-6-8.md)
- [Milestone G to H handoff](../handoffs/milestone-g-to-h.md)
- [Milestone H to I handoff](../handoffs/milestone-h-to-i.md)
- [Step 8.2 to 8.3 handoff](../handoffs/step-8-2-to-8-3.md)
