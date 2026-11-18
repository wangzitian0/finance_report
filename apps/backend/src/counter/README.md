# `counter` (backend implementation)
This is the **conforming backend implementation** of the `counter` package. The package's authoritative spec — ubiquitous language, invariants, roles, storage, and governance — lives in [`common/counter/`](../../../../common/counter/readme.md).
- Spec / ubiquitous language: [`common/counter/readme.md`](../../../../common/counter/readme.md)
- Package model: [`common/meta/readme.md`](../../../../common/meta/readme.md) The code here converges into the package model's layers — `base/` (pure core: `types/` nouns + events, `ops/` verbs over the repository port, `repository.py` the `CounterRepository` port) and `extension/` (the impure
edges: `sql.py` SQLAlchemy adapter, `facade/` the thin programmatic boundary) — and publishes its package root `__all__`.
