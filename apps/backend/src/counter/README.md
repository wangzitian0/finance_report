# `counter` (backend implementation)

This is the **conforming backend implementation** of the `counter` package
(`PackageContract.implementations["be"]`). The package's authoritative spec —
ubiquitous language, contract, roles, storage, and governance — lives in
[`common/counter/`](../../../../common/counter/readme.md).

- Spec / ubiquitous language: [`common/counter/readme.md`](../../../../common/counter/readme.md)
- Machine contract (interface, invariants, roadmap ACs): [`common/counter/contract.py`](../../../../common/counter/contract.py)
- Package model: [`common/meta/readme.md`](../../../../common/meta/readme.md)

The code here converges into the package model's layers — `base/` (pure core:
`types/` nouns + events, `ops/` verbs over the repository port,
`repository.py` the `CounterRepository` port) and `extension/` (the impure
edges: `sql.py` SQLAlchemy adapter, `api/` the thin async boundary) — and
publishes exactly its `__init__.__all__`, which must equal
`contract.interface`.
