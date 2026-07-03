# `coverage` — unified coverage policy + lcov helpers (infra tooling package)

> Internal tooling, not a domain bounded context. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).

## What

The unified-coverage policy and lcov toolchain: which source files are in scope per component, parsing/merging lcov, and failing CI when a registered source is missing from the report.

> **Scope note — this package owns the lcov/policy *tooling* only.** The broader
> unified-coverage *system* prose (CI-workflow integration, Coveralls reporting
> policy, frontend vitest coverage, the no-regression baseline gate) stays in
> [`docs/ssot/coverage.md`](../../docs/ssot/coverage.md) and is owned by EPIC-008
> (testing-strategy), whose ACs (`AC8.13.27` / `AC8.13.66` / `AC8.13.75`) assert
> against that doc. That surface is cross-cutting (backend + frontend + CI +
> Coveralls), not this narrow `infra` leaf's domain, so per the package-migration
> standard's "don't force a bad fit" it is **not** internalized here.

## Shape

An `infra` leaf (L1): no declared dependencies (`depends_on=[]`) and `tier=CODE-ONLY`
(pure Python, no LLM). It is a **collection of modules** invoked directly (and via
`tools/` wrappers), so it publishes **no curated symbol language** —
`contract.interface` is `[]`. Its [`contract.py`](./contract.py) is validated by
`tools/check_package_contract.py` (invariants pinned to tests (the DAG import-scan only inspects `src.<pkg>` imports, so for a `common/`-implemented package leaf-purity is a declared, not a scanned, property)).

## Follow-up

Curating a published `__all__` surface (so consumers import the package root, not
its submodules) is deferred — see [`todo.md`](./todo.md).
