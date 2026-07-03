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
[`common/meta/`](./meta/readme.md), checked by the very gate it
ships.

## Map

All 12 packages ship a `contract.py` and are discovered by
`tools/check_package_contract.py`; grouped by `klass` (the DAG tier — see
[`meta/readme.md`](./meta/readme.md#three-package-classes)):

- **`core`** (vertical domain slices): [`identity`](./identity/readme.md),
  [`ledger`](./ledger/readme.md)
- **`platform`** (reusable horizontal capabilities):
  [`meta`](./meta/readme.md) — the meta package: the package-model spec,
  `PackageContract`, and the governance gate;
  [`counter`](./counter/readme.md) — the first worked example, the canonical
  minimal template every new package copies (`readme.md` + `contract.py` +
  `todo.md`)
- **`kernel`** (the value-language/tooling layer reused everywhere):
  [`audit`](./audit/readme.md), [`authority`](./authority/readme.md),
  [`config`](./config/readme.md), [`coverage`](./coverage/readme.md),
  [`observability`](./observability/readme.md), [`platform`](./platform/readme.md)
  (the event-bus package — its *name* is `platform`, its *klass* is `kernel`),
  [`runtime`](./runtime/readme.md), [`testing`](./testing/readme.md)

Two directories are **not** packages (no `contract.py`) but are documented,
reasoned exceptions to `check_package_directory_coverage`'s every-directory
rule (see [`meta/readme.md`](./meta/readme.md)):

- `common/ssot/` — 3 leftover generator scripts with no clean package fit yet
  (`generate_api_reference.py`, `generate_db_schema_reference.py`,
  `generate_openapi_spec.py`).
- `common/extraction/`, `common/llm/` — SSOT-only today, pending their code
  cutovers (#1421, #1426).

[`common/todo.md`](./todo.md) is the cross-package / migration worklist.
