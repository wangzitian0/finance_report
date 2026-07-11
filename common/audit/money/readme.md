# `money` — Decimal money value language (kernel package)

> The money/currency/FX value type. Model spec:
> [`../../meta/readme.md`](../../meta/readme.md). Machine contract:
> [`contract.py`](../contract.py). Language-neutral interface + conformance:
> [`contract/money.contract.md`](./contract/money.contract.md) +
> [`conformance/vectors.json`](./conformance/vectors.json). Worklist:
> [`todo.md`](./todo.md).
>
> The **audit** package's value-language core (L1 `infra` in the five-layer
> map). It imports the `ratio` package
> (`MoneyTolerance` is a `Ratio`) — a declared, acyclic **same-layer** edge, which
> the package model allows ("never up, never sideways-cyclic").

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

`common/audit/money/` is the canonical value language; the runtime mirrors at
`apps/backend/src/audit/money` (`implementations["be"]`) and
`apps/frontend/src/lib/audit/money` (`implementations["fe"]`) must render the *same*
behaviour. Drift is prevented by the shared `conformance/vectors.json` — both ends
prove themselves against the same vectors.

## Governance

[`contract.py`](../contract.py) is validated by `tools/check_package_contract.py`:
`interface` == the BE `__all__`, every invariant pins to a conformance test, and
no upward/sideways import edge. The money ACs (`AC2.19.x` / `AC2.20.x`) are still
owned by the EPIC-002 table; moving that AC ownership into the contract `roadmap`
(so the contract is the single source) is a tracked follow-up — see
[`todo.md`](./todo.md).

---

## Money value types (narrow waist)

> Internalized here from the retired `docs/ssot/accounting.md#money-type` per the
> package-migration standard
> ([`../../meta/migration-standard.md`](../../meta/migration-standard.md), step 3 "SSOT
> internalized"). This is the registered owner of the `money_value_type` concept.

<a id="money-type"></a>

- **Rule A3 — Money value types (narrow waist)**: The application-layer money
  primitives live in **`common/audit/money/`** (the shared waist). They sit *above* the
  DB double-entry invariant floor (`fr_validate_journal_entry_invariants`,
  [schema.md](../../../docs/ssot/schema.md)) and make bad money states unrepresentable
  rather than merely tested-against (#1167). Dependency-light (stdlib + `Decimal`
  only) so backend, e2e, frontend helpers and tooling can share one definition. The
  backend ships its own self-contained copy at **`apps/backend/src/audit/money/`** (the
  backend's "end"; `common/` is not shipped into the image), kept in lockstep
  with the reference impl by the shared conformance vectors (#1171). Backend
  call-sites import `src.audit.money` directly (the former `src/utils/money.py`
  re-export shim was retired).
    -   **`Money(amount, currency)`** — immutable, `Decimal`-backed; construction
        **rejects `float`/`bool`** (the decimal red line, type-enforced) and stores
        the *exact* `Decimal` (round explicitly via `Money.quantize()` / the FX
        boundary, never force-quantized on construction).
    -   **`Currency`** — a validated ISO-4217 alphabetic code (not a bare `str`);
        normalises case and rejects unknown codes at construction.
    -   **`ExchangeRate(base, quote, rate)`** — the typed directed FX conversion
        parameter. `base` / `quote` are validated currencies; `rate` is finite,
        positive Decimal; **`float`/`bool` are rejected**.
    -   **Arithmetic** — same-currency `+`/`-`/comparison only; any cross-currency
        operation raises `CurrencyMismatchError`. No implicit conversion, no
        implicit `float`.
    -   **`convert(money, exchange_rate, rounding=ROUND_HALF_EVEN)`** — the
        **single** FX conversion primitive: `exchange_rate.base` must equal
        `money.currency`; the result currency is `exchange_rate.quote`; banker's
        rounding applies at the 2-dp boundary; used for base-currency restatement.
    -   **`CurrencyBalances`** — per-currency opening/closing container with **no
        scalar accessor**, so a multi-currency statement cannot collapse onto one
        currency (closes the #1139/#1123 representation gap); round-trips the
        `StatementSummary.currency_balances` JSONB shape.
    -   **Cross-language standard**: money behaviour is consistent across **every
        end** via a language-neutral conformance suite —
        `common/audit/money/conformance/vectors.json` (rounding/convert/currency cases)
        plus the interface in `common/audit/money/contract/money.contract.md`. The
        Python impl and the frontend TS impl (`apps/frontend/src/lib/audit/money/`) both
        load the **same** vectors and must reproduce every value, so the two ends
        cannot diverge (e.g. banker's rounding vs `decimal.js` HALF_UP). The suite
        is **dev/test-time only** — it is never shipped into a runtime image, which
        is why no app needs `common/` packaged into its container.
    -   **Guardrail (AC2.19–AC2.21)**: `tests/tooling/test_money_value_type.py`,
        `tests/tooling/test_money_conformance.py`.
