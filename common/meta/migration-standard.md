# Package Migration Standard

Authoritative target architecture for bounded contexts under `common/<pkg>/` (`common/meta/base/layering.py::PACKAGE_LAYER`). Contract files (`common/<pkg>/contract.py`, `readme.md`, optional `contract/` + `conformance/vectors.json`) live in `common/`; runtime code lives in `apps/backend/src/<pkg>/` and `apps/frontend/src/lib/<pkg>/`.

## Internal layering

Each package converges by **layer** (`KIND_LAYER` in `common/meta/base/package_contract.py`):
- **base**: Pure value objects, entities, domain events, and repository ports; no I/O or upward imports.
- **extension**: Impure repository adapters, domain services, ORM models, and transport/event publishers.
- **data**: CQRS read projections (leaf sinks, zero FK constraints into write tables, bitemporal + idempotent with provenance ids).

`check_app_boundary` prevents boundary leaks between domain packages and `routers/` / `schemas/` (**The app delivery layer**, baseline-ratcheted by `common/meta/data/delivery-layer-baseline.json` in `tests/tooling/test_delivery_layer_ratchet.py`).

## Cross-domain DB & AC rules

- Intra-domain FKs are free; cross-domain bare `ForeignKey` is allowed (`UserOwnedMixin` tenancy), cross-domain `relationship()` is banned; `ondelete="CASCADE"` is audited in `common/audit/data/fk-cascade-ownership.json`.
- ACs use `AC-<package>.<entity>.<seq>` inside `contract.py` `roadmap`, never duplicated in EPIC tables.

See: [`readme.md`](./readme.md) · [`contract.py`](./contract.py) · [`../../vision.md`](../../vision.md)
