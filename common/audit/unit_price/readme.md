# `unit_price` — money-per-unit value language (kernel package)
> The unit-price value type. Model spec: [`../../meta/readme.md`](../../meta/readme.md). Language-neutral interface + conformance: [`contract/unit_price.contract.md`](./contract/unit_price.contract.md) + [`conformance/vectors.json`](./conformance/vectors.json). An **audit** value language (L1 `infra`). It imports `money` and `quantity` (a `UnitPrice` is money per unit) — declared, acyclic same-class edges.
## Why
A price is "money per unit" (e.g. `12.34 SGD / share`). Multiplying a `UnitPrice` by a `Quantity` must yield `Money` deterministically, with the currency and unit checked — not a float multiply that loses precision or silently mixes currencies. `UnitPrice` makes that the only representable form.
## Ubiquitous language
- **`UnitPrice`** — an exact `Decimal` money-per-unit bound to a currency and a unit, quantized by `UNIT_PRICE_DP` / `UNIT_PRICE_QUANTUM` / `UNIT_PRICE_ROUNDING`. Float construction is unrepresentable (`FloatNotAllowedError`). - **product** — `UnitPrice` × `Quantity` → `Money`, rounded deterministically; a currency clash raises `CurrencyMismatchError` and a unit clash raises
  `UnitMismatchError`. - **undefined** — an undefined unit price raises `UndefinedUnitPriceError`.
## Public vs internal
**Public** (`__all__`, 9 symbols): `UnitPrice`, the constants, and the errors (`UnitPriceError`, `FloatNotAllowedError`, `UndefinedUnitPriceError`, `CurrencyMismatchError`, `UnitMismatchError`).
## Ends
`common/audit/unit_price/` is canonical and mirrored at `apps/backend/src/audit/unit_price`, kept honest by `conformance/vectors.json`. There is no frontend implementation yet.
## Governance
Conformance is verified against `conformance/vectors.json`.
