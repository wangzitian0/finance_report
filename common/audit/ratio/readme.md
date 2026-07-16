# `ratio` — Decimal ratio / percentage value language (kernel package)

> The ratio/percentage value type. Model spec:
> [`../../meta/readme.md`](../../meta/readme.md). Machine contract:
> [`contract.py`](../contract.py). Language-neutral interface + conformance:
> [`contract/ratio.contract.md`](./contract/ratio.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json).
>
> An **audit value-language leaf** (L1 `infra`) — it depends on nothing in the app, and is reused by
> `money` and `quantity`.

## Why

Percentages drift into floats and lose precision. `Ratio` makes a proportion an
exact `Decimal` value with one standard rendering (`PERCENT_DP` decimal places,
`PERCENT_ROUNDING`), so "1.5%", "apply 1.5% to a base", and round-tripping a
stored percentage are all deterministic and identical across BE and FE.

## Ubiquitous language

- **`Ratio`** — an exact `Decimal` proportion. Float construction is
  unrepresentable (`FloatNotAllowedError`); an undefined ratio (e.g. divide-by-zero
  origin) raises `UndefinedRatioError`.
- **percent rendering** — `to_percent()` / `from_percent()` use `PERCENT_DP` +
  `PERCENT_ROUNDING` so a percentage round-trips within the standard precision.
- **wire/db adapters** — `ratio_{to,from}_{wire,db_value}` convert at the boundary.

## Public vs internal

**Public** (`__all__` == `contract.interface`, 11 symbols): `Ratio`, the constants
`PERCENT_DP` / `PERCENT_ROUNDING`, the errors (`RatioError`, `FloatNotAllowedError`,
`InvalidRatioPayloadError`, `UndefinedRatioError`), and the wire/db adapters.

## Three ends, one spec

`common/audit/ratio/` is canonical; `apps/backend/src/audit/ratio` and
`apps/frontend/src/lib/audit/ratio` mirror it. The shared `conformance/vectors.json`
keeps the two ends from drifting.

## Governance

[`contract.py`](../contract.py) is validated by `tools/check_package_contract.py`
(interface == BE `__all__`, invariants pin to conformance tests, no forbidden
import edge). The ratio ACs formerly named `AC12.9.x` are owned by the audit
contract roadmap as `AC-audit.9.*`; the EPIC contains no mirrored rows.
