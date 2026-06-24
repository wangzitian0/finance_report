# `quantity` — Decimal quantity + unit value language (platform package)

> The quantity/unit value type. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Language-neutral interface + conformance:
> [`contract/quantity.contract.md`](./contract/quantity.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json). Worklist:
> [`todo.md`](./todo.md).
>
> Classed **`platform`** because it imports the `ratio` kernel package (a `Ratio`
> can scale a `Quantity`), so it sits one layer above `ratio`.

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

`common/quantity/` is canonical; `apps/backend/src/quantity` and
`apps/frontend/src/lib/quantity` mirror it, kept in sync by
`conformance/vectors.json`.

## Governance

[`contract.py`](./contract.py) is validated by `tools/check_package_contract.py`
(interface == BE `__all__`, invariants pin to conformance tests, no forbidden
import edge). The quantity ACs (`AC12.30.x`) are still owned by EPIC-012; moving
them into the contract `roadmap` is a tracked follow-up — see [`todo.md`](./todo.md).
