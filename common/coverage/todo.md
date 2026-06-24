# `coverage` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Migrated to the package model: ships `contract.py`, governed by
      `check_package_contract` as a `kernel` leaf (zero cross-package imports)
      with invariants pinned to its tests.

## Next

- [ ] Curate a published `__all__` surface and set `contract.interface`, so
      consumers import the package root instead of its submodules (today this is
      a module-collection with `interface=[]`).
