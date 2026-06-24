# `observability` — OpenPanel query CLI (kernel tooling package)

> Internal tooling, not a domain bounded context. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).

## What

A thin CLI to query the OpenPanel analytics API (funnels/filters), reading credentials from the environment.

## Shape

A `kernel` leaf: no declared dependencies (`depends_on=[]`) and `tier=CODE-ONLY`
(pure Python, no LLM). It is a **collection of modules** invoked directly (and via
`tools/` wrappers), so it publishes **no curated symbol language** —
`contract.interface` is `[]`. Its [`contract.py`](./contract.py) is validated by
`tools/check_package_contract.py` (invariants pinned to tests (the DAG import-scan only inspects `src.<pkg>` imports, so for a `common/`-implemented package leaf-purity is a declared, not a scanned, property)).

## Follow-up

Curating a published `__all__` surface (so consumers import the package root, not
its submodules) is deferred — see [`todo.md`](./todo.md).
