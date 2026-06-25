# `common/` — cross-package / migration worklist

The horizontal worklist for rolling the package model across `common/`. Each
package also keeps its own `common/<pkg>/todo.md` for package-local work; this
file tracks the migration *between* packages and the phase order.

## Migration phases

The model lands one tier at a time, lowest-risk first. `counter` is the proven
template; everything else copies its shape (`readme.md` + `contract.py` +
`todo.md`, implementation under `apps/`).

| phase | packages | klass | status |
|-------|----------|-------|--------|
| 0 — template | `counter` | platform | ✅ canonical template (`readme`+`contract`+`todo`, AC from contract) |
| 0 — meta | `meta` | platform | ✅ self-hosts the model |
| 1 — kernel | `money`, `ratio`, `quantity`, `unit_price` | kernel | ⬜ adopt `PackageContract` (leaf value language) |
| 2 — platform | `ci`, `observability`, `shell`, `testing`, `coverage` | platform | ⬜ delivery / environments / observability capabilities |
| 3 — core | portfolio, ledger, reconciliation, reporting | core | ⬜ vertical domain slices adopt contracts (ledger already prototypes roles/DAG) |

## Conventions every migration must keep

- A package's ACs live in its `contract.py` `roadmap`, **never** mirrored into an
  EPIC table (the AC registry sources them additively).
- `contract.interface` must equal the BE implementation's `__init__.__all__`.
- `implementations` points at the real code dirs; `roles` lists the role folders.
- Adding a package adds no central index edit — shipping `common/<pkg>/contract.py`
  is what registers it with the governance gate.

## Now / next

- [x] `counter` becomes the `common/`-centric template (this change).
- [x] `meta` self-hosts (`common/meta/readme.md` + `contract.py`).
- [ ] Phase 1: give each kernel package a `common/<pkg>/contract.py` + `readme.md`.
- [ ] Decide the `core` package boundaries (portfolio vs ledger vs reporting) and
      sequence their contract adoption.
