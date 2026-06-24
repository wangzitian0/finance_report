# `money` — Decimal money value language (platform package)

> The money/currency/FX value type. Model spec:
> [`../governance/readme.md`](../governance/readme.md). Machine contract:
> [`contract.py`](./contract.py). Language-neutral interface + conformance:
> [`contract/money.contract.md`](./contract/money.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json). Worklist:
> [`todo.md`](./todo.md).
>
> A **kernel-style value language**, but classed **`platform`** because it imports
> the `ratio` kernel package (`MoneyTolerance` is a `Ratio`) — so it sits one
> layer above `ratio` in the dependency DAG.

## Why

Money is never a `float` (the #1 red line). This package makes correct money the
*only representable* money: a `Money` is an exact `Decimal` amount bound to a
validated ISO-4217 `Currency`, rounded with banker's `HALF_EVEN` to the currency's
minor unit. Cross-currency math must go through an explicit `ExchangeRate`; you
cannot add two different currencies by accident.

## Ubiquitous language

- **`Money`** — an exact `Decimal` amount + a `Currency`. Float construction is
  unrepresentable (`FloatNotAllowedError`); a mismatched-currency operation raises
  `CurrencyMismatchError`.
- **`Currency`** — a validated ISO-4217 code (`ISO_4217_CODES`); an invalid code
  is unrepresentable (`InvalidCurrencyError`). `MONEY_QUANTUM` is the rounding step.
- **`ExchangeRate`** — a directed, validated rate; `convert()` applies it and
  rounds deterministically (`InvalidExchangeRateError` guards bad rates).
- **`CurrencyBalances` / `CurrencyBalance`** — a multi-currency balance bag.
- **`MoneyTolerance`** — an absolute+relative band (a `Ratio`) for "are these two
  amounts close enough" in matching/reconciliation.
- **wire/db adapters** — `money_{to,from}_{wire,db_fields}`,
  `exchange_rate_{to,from}_{wire,db_fields}`, `to_money` convert at the boundary.

## Public vs internal

**Public** (`__all__` == `contract.interface`, 24 symbols): the types above +
`MoneyError` and the typed errors + `convert` + the wire/db adapters. Everything
else (`guard.py`, `rounding.py` internals) is implementation detail.

## Three ends, one spec

`common/money/` is the canonical value language; the runtime mirrors at
`apps/backend/src/money` (`implementations["be"]`) and
`apps/frontend/src/lib/money` (`implementations["fe"]`) must render the *same*
behaviour. Drift is prevented by the shared `conformance/vectors.json` — both ends
prove themselves against the same vectors.

## Governance

[`contract.py`](./contract.py) is validated by `tools/check_package_contract.py`:
`interface` == the BE `__all__`, every invariant pins to a conformance test, and
no upward/sideways import edge. The money ACs (`AC2.19.x` / `AC2.20.x`) are still
owned by the EPIC-002 table; moving that AC ownership into the contract `roadmap`
(so the contract is the single source) is a tracked follow-up — see
[`todo.md`](./todo.md).
