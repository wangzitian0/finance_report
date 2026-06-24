# `coverage` — unified coverage policy + lcov helpers (kernel tooling package)

> Internal tooling, not a domain bounded context. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).

## What

The unified-coverage policy and lcov toolchain: which source files are in scope per component, parsing/merging lcov, and failing CI when a registered source is missing from the report.

## Shape

A `kernel` leaf: **zero cross-package imports** (gate-enforced) and `tier=CODE-ONLY`
(pure Python, no LLM). It is a **collection of modules** invoked directly (and via
`tools/` wrappers), so it publishes **no curated symbol language** —
`contract.interface` is `[]`. Its [`contract.py`](./contract.py) is validated by
`tools/check_package_contract.py` (leaf-DAG purity + invariants pinned to tests).

## Follow-up

Curating a published `__all__` surface (so consumers import the package root, not
its submodules) is deferred — see [`todo.md`](./todo.md).
