# `quantity` — Decimal quantity + unit value language (kernel package)
> The quantity/unit value type. Model spec: [`../../meta/readme.md`](../../meta/readme.md). Language-neutral interface + conformance: [`contract/quantity.contract.md`](./contract/quantity.contract.md) + [`conformance/vectors.json`](./conformance/vectors.json). An **audit** value language (L1 `infra`). It imports `ratio` (a `Ratio` can scale a `Quantity`) — a declared, acyclic same-class edge.
## Why
A holding of "10.5 shares" or "3 units" is an exact `Decimal` amount bound to a `Unit` — never a float, and never silently mixing incompatible units. `Quantity` makes that the only representable form, with one standard quantization (`QUANTITY_DP` / `QUANTITY_QUANTUM` / `QUANTITY_ROUNDING`).
## Ubiquitous language
- **`Quantity`** — an exact `Decimal` amount + a `Unit`. Float construction is unrepresentable (`FloatNotAllowedError`). - **`Unit`** — the validated unit of measure; an invalid unit is unrepresentable (`InvalidUnitError`), and combining mismatched units raises `UnitMismatchError`. - **scaling** — applying a `Ratio` to a `Quantity` rounds deterministically.
## Public vs internal
**Public** (`__all__`, 9 symbols): `Quantity`, `Unit`, the constants (`QUANTITY_DP` / `QUANTITY_QUANTUM` / `QUANTITY_ROUNDING`), and the errors (`QuantityError`, `FloatNotAllowedError`, `InvalidUnitError`, `UnitMismatchError`).
## Three ends, one spec
`common/audit/quantity/` is canonical; `apps/backend/src/audit/quantity` and `apps/frontend/src/lib/audit/quantity` mirror it, kept in sync by `conformance/vectors.json`.
## Governance
Cross-end conformance is verified against `conformance/vectors.json`.
