# `config` — env-key + schema validation helpers (kernel tooling package)

> Internal tooling, not a domain bounded context. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).

## What

Helpers that validate environment-key definitions across the secrets template, `.env.example`, and `config.py`, and validate schema files for consistency.

## Shape

A `kernel` leaf: **zero cross-package imports** (gate-enforced) and `tier=CODE-ONLY`
(pure Python, no LLM). It is a **collection of modules** invoked directly (and via
`tools/` wrappers), so it publishes **no curated symbol language** —
`contract.interface` is `[]`. Its [`contract.py`](./contract.py) is validated by
`tools/check_package_contract.py` (leaf-DAG purity + invariants pinned to tests).

## Follow-up

Curating a published `__all__` surface (so consumers import the package root, not
its submodules) is deferred — see [`todo.md`](./todo.md).
