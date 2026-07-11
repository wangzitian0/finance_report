# `unit_price` — money-per-unit value language (kernel package)

> The unit-price value type. Model spec:
> [`../../meta/readme.md`](../../meta/readme.md). Machine contract:
> [`contract.py`](../contract.py). Language-neutral interface + conformance:
> [`contract/unit_price.contract.md`](./contract/unit_price.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json). Worklist:
> [`todo.md`](./todo.md).
>
> An **audit** value language (L1 `infra`). It imports `money` and `quantity` (a `UnitPrice`
> is money per unit) — declared, acyclic same-class edges, which the model allows.

## Why

A price is "money per unit" (e.g. `12.34 SGD / share`). Multiplying a `UnitPrice`
by a `Quantity` must yield `Money` deterministically, with the currency and unit
checked — not a float multiply that loses precision or silently mixes currencies.
`UnitPrice` makes that the only representable form.

## Ubiquitous language

- **`UnitPrice`** — an exact `Decimal` money-per-unit bound to a currency and a
  unit, quantized by `UNIT_PRICE_DP` / `UNIT_PRICE_QUANTUM` / `UNIT_PRICE_ROUNDING`.
  Float construction is unrepresentable (`FloatNotAllowedError`).
- **product** — `UnitPrice` × `Quantity` → `Money`, rounded deterministically;
  a currency clash raises `CurrencyMismatchError` and a unit clash raises
  `UnitMismatchError`.
- **undefined** — an undefined unit price raises `UndefinedUnitPriceError`.
- **wire/db adapters** — `unit_price_{to,from}_{wire,db_fields}` convert at the
  boundary.

## Public vs internal

**Public** (`__all__` == `contract.interface`, 14 symbols): `UnitPrice`, the
constants, the errors (`UnitPriceError`, `FloatNotAllowedError`,
`InvalidUnitPricePayloadError`, `UndefinedUnitPriceError`, `CurrencyMismatchError`,
`UnitMismatchError`), and the wire/db adapters.

## Ends

`common/audit/unit_price/` is canonical and mirrored at `apps/backend/src/audit/unit_price`
(`implementations["be"]`), kept honest by `conformance/vectors.json`. There is no
frontend implementation yet, so `implementations["fe"]` is `None`.

## Governance

[`contract.py`](../contract.py) is validated by `tools/check_package_contract.py`
(interface == BE `__all__`, invariants pin to conformance tests, no forbidden
import edge — it may import the same-class `money` and `quantity` packages,
declared in `depends_on` and acyclic). The unit_price ACs (`AC12.32.x`) are still owned by
EPIC-012; moving them into the contract `roadmap` is a tracked follow-up — see
[`todo.md`](./todo.md).
