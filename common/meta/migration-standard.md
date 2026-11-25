# Package Migration Standard

Authoritative target architecture for bounded contexts under `common/<pkg>/` (`common/meta/base/layering.py::PACKAGE_LAYER`). Package specifications (`readme.md`, optional `contract/` + `conformance/vectors.json`) live in `common/`; runtime code lives in `apps/backend/src/<pkg>/` and `apps/frontend/src/lib/<pkg>/`.

## Internal layering

Each package converges by **layer**:
- **base**: Pure value objects, entities, domain events, and repository ports; no I/O or upward imports.
- **extension**: Impure repository adapters, domain services, ORM models, and transport/event publishers.
- **data**: CQRS read projections (leaf sinks, zero FK constraints into write tables, bitemporal + idempotent with provenance ids).

`check_app_boundary` prevents boundary leaks between domain packages and `routers/` / `schemas/` (**The app delivery layer**).

## Cross-domain DB & flow rules

- Intra-domain FKs are free; cross-domain bare `ForeignKey` is allowed (`UserOwnedMixin` tenancy), cross-domain `relationship()` is banned.
- End-to-end business user cases live in `common/meta/flows/user_cases_ssot.json`, never duplicated in EPIC tables.

See: [`readme.md`](./readme.md) · [`../../vision.md`](../../vision.md)
