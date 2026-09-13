# Architecture Documentation

This directory will hold concise, implementation-aligned architecture records
for the Premier League prediction platform.

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
- [Point-in-time feature processing](../features/point-in-time.md)
- [Probabilistic development evaluation](../models/probabilistic-evaluation.md)
- [Simulation domain, scorelines and table rules](../simulation/domain-and-table.md)
- [Implementation roadmap](../roadmap.md)
- [Project status](../project-status.md)
- [Milestone B to C handoff](../handoffs/milestone-b-to-c.md)
- [Milestone C to D handoff](../handoffs/milestone-c-to-d.md)
- [Milestone D to E handoff](../handoffs/milestone-d-to-e.md)
