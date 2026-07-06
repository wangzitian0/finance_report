# `counter` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] First worked example of the package model (the then-role folders `types`/`ops`/`store`/`api`,
      `PackageContract`, `__all__` published language).
- [x] Become the `common/`-centric template: spec (`readme.md` + `contract.py` +
      `todo.md`) under `common/counter/`, implementation under
      `apps/backend/src/counter`.
- [x] ACs (`AC-counter.1.1`–`AC-counter.1.4`) sourced directly from the contract `roadmap`.

## Next

- [ ] Add a frontend implementation (`apps/frontend/src/lib/counter`) and set
      `implementations["fe"]` so insight reports can read counts client-side.
- [ ] Publish a typed read API surface for global counts consumed by reporting.
- [ ] Add a `count_decremented` / void path if a future use case needs reversible
      tallies (today counts are monotonic by design).
