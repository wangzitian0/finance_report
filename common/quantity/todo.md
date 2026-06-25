# `quantity` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Decimal-only quantity + unit value language with one standard quantization.
- [x] Three-end parity (`common/` canonical + BE/FE mirrors) enforced by
      `conformance/vectors.json`.
- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract`. Classed `kernel` (imports `ratio` as a declared,
      acyclic same-class edge).

## Next

- [ ] Move the quantity ACs (`AC12.30.x`) out of the EPIC-012 table into the
      contract `roadmap`, so the contract is the single AC source.
