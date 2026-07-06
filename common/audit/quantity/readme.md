# `quantity` — Decimal quantity + unit value language (kernel package)

> The quantity/unit value type. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Language-neutral interface + conformance:
> [`contract/quantity.contract.md`](./contract/quantity.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json). Worklist:
> [`todo.md`](./todo.md).
>
> An **audit** value language (L1 `infra`). It imports `ratio` (a `Ratio` can scale a
> `Quantity`) — a declared, acyclic same-class edge, which the package model allows.

## Why

A holding of "10.5 shares" or "3 units" is an exact `Decimal` amount bound to a
`Unit` — never a float, and never silently mixing incompatible units. `Quantity`
makes that the only representable form, with one standard quantization
(`QUANTITY_DP` / `QUANTITY_QUANTUM` / `QUANTITY_ROUNDING`).

## Ubiquitous language

- **`Quantity`** — an exact `Decimal` amount + a `Unit`. Float construction is
  unrepresentable (`FloatNotAllowedError`).
- **`Unit`** — the validated unit of measure; an invalid unit is unrepresentable
  (`InvalidUnitError`), and combining mismatched units raises `UnitMismatchError`.
- **scaling** — applying a `Ratio` to a `Quantity` rounds deterministically.
- **wire/db adapters** — `quantity_{to,from}_{wire,db_fields}` convert at the
  boundary.

## Public vs internal

**Public** (`__all__` == `contract.interface`, 14 symbols): `Quantity`, `Unit`,
the constants (`QUANTITY_DP` / `QUANTITY_QUANTUM` / `QUANTITY_ROUNDING`), the
errors (`QuantityError`, `FloatNotAllowedError`, `InvalidQuantityPayloadError`,
`InvalidUnitError`, `UnitMismatchError`), and the wire/db adapters.

## Three ends, one spec

`common/audit/quantity/` is canonical; `apps/backend/src/audit/quantity` and
`apps/frontend/src/lib/audit/quantity` mirror it, kept in sync by
`conformance/vectors.json`.

## Governance

[`contract.py`](./contract.py) is validated by `tools/check_package_contract.py`
(interface == BE `__all__`, invariants pin to conformance tests, no forbidden
import edge). The quantity ACs (`AC12.30.x`) are still owned by EPIC-012; moving
them into the contract `roadmap` is a tracked follow-up — see [`todo.md`](./todo.md).
