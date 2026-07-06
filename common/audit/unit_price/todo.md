# `unit_price` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Decimal-only money-per-unit value language; `UnitPrice` × `Quantity` → `Money`
      with currency/unit checks.
- [x] Backend parity (`common/` canonical + BE mirror) enforced by
      `conformance/vectors.json`.
- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract`. Classed `kernel` (then-klass, since retired; imports `money` + `quantity` as
      declared, acyclic same-class edges).

## Next

- [ ] Move the unit_price ACs (`AC12.32.x`) out of the EPIC-012 table into the
      contract `roadmap`, so the contract is the single AC source.
- [ ] Add a frontend implementation (`apps/frontend/src/lib/audit/unit_price`) and set
      `implementations["fe"]`, with FE conformance against the shared vectors.
