# `observability` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract` as a `kernel` package (then-klass, since retired; `depends_on=["config"]` —
      the OTEL runtime reads the backend config singleton) with invariants pinned
      to its tests.
- [x] Curated a published `__all__` surface and set `contract.interface`: the BE
      implementation (`apps/backend/src/observability`) now publishes the OTEL
      runtime contract + the shared audit/security logging helpers, so consumers
      import the package root (`from src.observability import ...`).

- [x] #1428: identity's `bind_authenticated_user_context` was folded into the
      `identity` package (`src/identity/extension/observability.py`) and
      `src.observability_events` deleted with zero residue.

## Next

- [ ] (none currently)
