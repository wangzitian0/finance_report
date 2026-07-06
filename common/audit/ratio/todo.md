# `ratio` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Decimal-only ratio/percentage value language with one standard rendering
      (`PERCENT_DP` / `PERCENT_ROUNDING`).
- [x] Three-end parity (`common/` canonical + BE/FE mirrors) enforced by
      `conformance/vectors.json`.
- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract`. Classed `kernel` (then-klass, since retired; a true leaf — depends on nothing).

## Next

- [ ] Move the ratio ACs (`AC12.9.x`) out of the EPIC-012 table into the contract
      `roadmap`, so the contract is the single AC source.
