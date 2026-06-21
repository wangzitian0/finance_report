# `common/` — the package review surface

`common/` is where the repo's **packages** live as specs and high-level review
surfaces. A package is a DDD bounded context; each one is a directory
`common/<pkg>/` holding its `readme.md` (ubiquitous language), `contract.py` (a
machine-checkable `PackageContract`), and `todo.md` (its worklist). The running
code is a conforming *implementation* the contract points at — under
`apps/backend/src/<pkg>` and/or `apps/frontend/src/lib/<pkg>`.

## The package model in a paragraph

`common/<pkg>/` is the authoritative **spec + review surface**; the apps hold the
**implementations**. A package declares one `klass` (`kernel` < `platform` <
`core`) that fixes its place in a down-only dependency DAG, converges its files by
**role** (`types`/`ops`/`store`/`api`), and publishes exactly its
`__init__.__all__` (which must equal `contract.interface`). Governance is
**computed from contracts, not authored**: `tools/check_package_contract.py`
discovers every `common/*/contract.py`, checks the implementation against it
(interface == `__all__`, every invariant/roadmap test resolves, no forbidden
dependency edge), and the AC registry sources each package's ACs straight from
its `roadmap` — so a package's ACs are never mirrored into an EPIC table. The
model **self-hosts**: the meta package that defines all of this is
[`common/governance/`](./governance/readme.md), checked by the very gate it
ships.

## Map

- [`common/governance/`](./governance/readme.md) — the meta package: the
  package-model spec, `PackageContract`, and the governance gate.
- [`common/counter/`](./counter/readme.md) — the first worked example
  (`platform`): the canonical minimal template every new package copies
  (`readme.md` + `contract.py` + `todo.md`).
- [`common/todo.md`](./todo.md) — the cross-package / migration worklist.

The other `common/*` directories (`ci`, `ssot`, `coverage`, `money`, `ratio`,
`quantity`, `unit_price`, `observability`, `shell`, `testing`, …) are existing
shared code; they adopt a full `contract.py` as the model rolls out (see the
phase table in [`todo.md`](./todo.md)).
