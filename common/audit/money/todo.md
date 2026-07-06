# `money` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Decimal-only money/currency/FX value language with banker's rounding and
      explicit `ExchangeRate` conversion.
- [x] Three-end parity (`common/` canonical + BE/FE mirrors) enforced by
      `conformance/vectors.json`.
- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract` (interface == `__all__`, DAG, invariants).

## Next

- [ ] Move the money ACs (`AC2.19.x` / `AC2.20.x`) out of the EPIC-002 table into
      the contract `roadmap`, so the contract is the single AC source (the model
      forbids mirroring an AC into both an EPIC and a roadmap).

## Done (class)

- [x] Classed `kernel` (then-klass, since retired; audit L1 today) — the value-language layer. It imports `ratio` as a
      declared, acyclic same-class edge — allowed by the package model's
      "never up, never sideways-cyclic" rule (no longer forced to `platform`).
