# `observability` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract` as a `kernel` leaf (`depends_on=[]`)
      with invariants pinned to its tests.
- [x] Curated a published `__all__` surface and set `contract.interface`: the BE
      implementation (`apps/backend/src/observability`) now publishes the OTEL
      runtime contract + the shared audit/security logging helpers, so consumers
      import the package root (`from src.observability import ...`).

## Next

- [ ] #1428: fold identity's `bind_authenticated_user_context` out of
      `src.observability_events` so that module is deleted with zero residue.
