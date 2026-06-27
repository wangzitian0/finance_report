# `audit` — the number governor

> The **number** governor, the parallel peer to [`meta`](../meta/readme.md) the
> **form** governor. `meta.base` is the package model everyone's *structure*
> conforms to; `audit.base` is the **value language** everyone's *numbers* are
> expressed in. Both are foundational *and* governing — one for form, one for
> number (the "meta / audit symmetry" in
> [`../meta/migration-standard.md`](../meta/migration-standard.md)).

## What audit governs

- **`audit.base`** — the value language: the cross-runtime Shared-Kernel value
  types (`Money` / `Currency` / `ExchangeRate` / `MoneyTolerance` /
  `CurrencyBalances` / `Ratio` / `Quantity` / `Unit` / `UnitPrice`), plus audit's
  own base value objects (financial invariants, confidence / provenance, trace
  records — the "governs number" core, a later fold).
- **`audit.extension`** — reaches the financial flow (`ledger` / `extraction` /
  `portfolio` / `reporting`) to assert global numeric correctness and end-to-end
  traceability (a later fold; closeout #1429).
- **`audit.data`** — confidence / provenance rollups and the trace-record index
  (a later fold).

Everyone's `base` ultimately depends on `audit.base` (the value types), so
`audit.extension` reaching the whole flow is what lets audit govern the numbers —
the symmetric mirror of `meta.extension` reaching every package to govern
structure.

## The Shared Kernel stays where it is

The four value packages (`money` / `ratio` / `quantity` / `unit_price`) are a
cross-runtime **Shared Kernel**: a language-neutral standard
(`common/<pkg>/contract/*.contract.md` + `conformance/vectors.json`) with a
canonical Python reference in `common/<pkg>` and per-end mirrors in
`apps/backend/src/<pkg>` and `apps/frontend/src/lib/<pkg>`, kept in lockstep by
the conformance vectors. That is exactly what `common/` is for — code whose
strategic role is "shared by everyone" (see
[`../meta/migration-standard.md`](../meta/migration-standard.md) "Where files
go"). The value→audit fold therefore **declares** these types as audit's value
language (its `units`) and **homes audit's numeric invariants against the same
conformance suites**; it does **not** relocate the value-package code, and it does
**not** touch the conformance vectors or the BE/FE parity. Backward compatibility
of those contracts is sacred.

The membership rule for what earns a Shared-Kernel value package, and the
per-package value contract, stay in the base-packages SSOT.
See: docs/ssot/base-packages.md

Monetary values are `Decimal`-backed and never use `float`; money rounds with
banker's `HALF_EVEN`. audit's `no-float-in-money-narrow-waist` invariant pins this
to the existing narrow-waist guard test. See: docs/ssot/accounting.md#decimal-rule

## Migration state (this fold)

This first, low-risk fold (issue #1419, Stage 1 of umbrella #1416):

- **Done here** — `audit` is registered as a package (this `contract.py`),
  declares the Shared Kernel as its value-object `units`, and pins six
  number-governor `invariants` to the existing, already-green conformance/guard
  tests (`test_{money,ratio,quantity,unit_price}_conformance.py` +
  `test_money_narrow_waist_guard.py`). The gate
  (`tools/check_package_contract.py`) validates audit alongside every other
  package.
- **Deferred (separate atomic cutover)** — transferring AC *ownership* of the
  value-language ACs (`AC2.19`/`AC2.20` in EPIC-002, `AC12.9`/`AC12.30`/`AC12.32`/
  `AC12.33`/`AC12.36` in EPIC-012) into audit's `roadmap`. Those ACs are
  registry-tracked and wired into `@ac_proof` edges, the per-type PROTECTION count
  floor, the tier baseline, and the BE/FE traceability references; re-homing them
  must atomically rename every such reference so the protection floor never drops.
  That is its own transaction (one per domain), tracked in [`todo.md`](./todo.md).
  `roadmap` stays empty until then — no AC may live in both an EPIC table and a
  package roadmap (`check_epic_package_dual` enforces it), exactly as the `money`
  contract documents today.
- **Also deferred** — audit's own base value objects (invariants / confidence /
  provenance / trace) and the `extension` reach into the financial flow.

## See also

- [`../meta/readme.md`](../meta/readme.md) — the form governor and the package
  model audit conforms to.
- [`../meta/migration-standard.md`](../meta/migration-standard.md) — the target
  architecture and the value→audit fold (meta / audit symmetry).
- `contract.py` — audit's machine-checkable `PackageContract`.
- [`../../vision.md`](../../vision.md) — the north star (Good Taste: backward
  compatibility of the value contracts is sacred).
