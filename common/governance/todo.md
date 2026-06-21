# `governance` — todo

The meta package's own worklist. Cross-package migration lives in
[`../todo.md`](../todo.md); this is scoped to the governance machinery itself.

## Now

- [x] Self-host the package-model spec here (`readme.md`) instead of a special
      `docs/ssot/` doc.
- [x] Ship a `PackageContract` for the governance package (`contract.py`), checked
      by its own gate.
- [x] Extend `PackageContract` with `status`, `roles`, `implementations`; discover
      contracts at `common/*/contract.py`; resolve `interface` against
      `implementations["be"]`.
- [x] Source ACs additively from package-contract `roadmap`s (no EPIC mirror).

## Next

- [ ] Add a `roadmap` to the governance contract once the model-evolution ACs are
      framed (currently invariants-only).
- [ ] Teach the gate to also validate `implementations["fe"]`'s published surface
      when a package ships a frontend implementation.
- [ ] Enforce `roles` against the implementation's actual role folders (today
      `roles` is descriptive; make it checked).
- [ ] Validate `depends_on` against `klass` rank declaratively in the contract,
      not only by scanning imports.
