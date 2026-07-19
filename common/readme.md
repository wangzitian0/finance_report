# `common/` — the package review surface

`common/` is where the repo's **packages** live as specs and high-level review
surfaces. A package is a DDD bounded context; each one is a directory
`common/<pkg>/` holding its `readme.md` (ubiquitous language) and `contract.py`
(a machine-checkable `PackageContract`). The running
code is a conforming *implementation* the contract points at — under
`apps/backend/src/<pkg>` and/or `apps/frontend/src/lib/<pkg>` (a project-wide
shared package implements directly in `common/<pkg>/`, e.g. `meta`).

## The package model in a paragraph

`common/<pkg>/` is the authoritative **spec + review surface**; the apps hold the
**implementations**. Placement in the five-layer topology (`meta` < `infra` <
`middleware` < `domain` < `app`) is global and owned by L0's central map
(`common/meta/base/layering.py` `PACKAGE_LAYER`), fixing a down-only dependency
DAG. Internally a package converges into three **layers** — `base` (pure core,
no I/O) / `extension` (impure cross-package edges) / `data` (read-model sink) —
and publishes exactly its `__init__.__all__` (which must equal
`contract.interface`). Governance is **computed from contracts, not authored**:
`check_package_contract` discovers every `common/*/contract.py`, checks the
implementation against it (interface == `__all__`, every invariant/roadmap test
resolves, no forbidden dependency edge), and the AC registry sources each
package's ACs straight from its `roadmap` — so a package's ACs are never
mirrored into an EPIC table. The model **self-hosts**: the meta package that
defines all of this is [`common/meta/`](./meta/readme.md), checked by the very
gate it ships.

## Map

Contract-carrying packages, by layer (see
[`meta/migration-standard.md`](./meta/migration-standard.md) for each package's
scope):

- **L0 meta** — [`meta/`](./meta/readme.md): the package-model spec,
  `PackageContract`, and the governance gate.
- **L1 infra** — [`audit/`](./audit/readme.md) (financial base types +
  `ExchangeRate` conversion math + numeric governance; absorbed the old
  money/ratio/quantity/unit_price value packages),
  [`llm/`](./llm/readme.md), [`observability/`](./observability/readme.md),
  [`platform/`](./platform/readme.md) (event-bus/outbox substrate,
  historically labelled *middleware*), [`runtime/`](./runtime/readme.md)
  (absorbed the old `config` package — env-key/schema-validation helpers,
  #1669),
  [`testing/`](./testing/readme.md) (absorbed the old `authority` and
  `coverage` packages, #1626).
- **L2 middleware** — [`counter/`](./counter/readme.md): the first worked
  example, the canonical minimal template every new package copies.
- **L3 domain** — [`advisor/`](./advisor/readme.md),
  [`extraction/`](./extraction/readme.md), [`identity/`](./identity/readme.md),
  [`ledger/`](./ledger/readme.md), [`portfolio/`](./portfolio/readme.md),
  [`pricing/`](./pricing/readme.md) (the one price/valuation SSOT;
  physical-table unification continues under #1610),
  [`reconciliation/`](./reconciliation/readme.md), [`reporting/`](./reporting/readme.md).
  All eight are `status="active"`.
The old `common/ci` / `common/shell` / `common/ssot` junk drawers are retired.
New shared tooling now lives in the package that owns the contract, and
`check_package_directory_coverage` fails any new undeclared `common/<dir>/`.
