# Money module contract (language-neutral interface)

> The **interface** half of the money module's SSOT. The **conformance** half is
> [`../conformance/vectors.json`](../conformance/vectors.json). Authoritative
> prose: [`docs/ssot/accounting.md#money-type`](../../../docs/ssot/accounting.md).
>
> This describes *what every implementation must expose and obey* — independent of
> language. Each stack (Python `common/money`, TypeScript `apps/frontend/src/lib/money`)
> renders this contract idiomatically and proves it via the conformance vectors.

## Types

- **`Currency`** — a validated ISO-4217 alphabetic code.
  - Normalises input (`strip` + upper-case) before validation.
  - Rejects anything not in the active ISO-4217 alphabetic set.
- **`Money`** — an immutable `(amount, currency)` pair.
  - `amount` is an arbitrary-precision decimal. **`float` is rejected** at
    construction (IEEE-754 precision loss). The exact value is stored — no
    force-quantize on construction.
- **`ExchangeRate`** — an immutable directed FX rate `(base, quote, rate)`.
  - `rate` is expressed as `amount_quote = amount_base * rate`.
  - `base` / `quote` are validated `Currency` values.
  - `rate` is a finite positive Decimal. **`float` is rejected**.

## Operations & laws

| Operation | Law |
|-----------|-----|
| construct `Money(amount, currency)` | rejects float; rejects non-ISO currency; immutable |
| `add` / `subtract` | **same-currency only**; cross-currency ⇒ typed error (no implicit conversion) |
| `compare` (`<`,`≤`,`>`,`≥`) | same-currency only; cross-currency ⇒ typed error |
| `equals` | cross-currency compares **unequal**, never an implicit collapse |
| `quantize(rounding)` | 2 dp; default **banker's rounding** (`ROUND_HALF_EVEN`) |
| `convert(money, exchange_rate, rounding)` | the **single** FX primitive; `exchange_rate.base` must equal `money.currency`; result currency is `exchange_rate.quote`; quantized at the 2-dp boundary |
| `money_to_wire` / `money_from_wire` | JSON boundary; amount is a decimal string and currency is an ISO-4217 string; JSON numbers are rejected |
| `exchange_rate_to_wire` / `exchange_rate_from_wire` | JSON boundary for directed FX rates; rate is a decimal string; JSON numbers are rejected |
| `money_to_db_fields` / `money_from_db_fields` | DB boundary for Python/backend code; amount is an exact `Decimal`, currency is a string |
| `exchange_rate_to_db_fields` / `exchange_rate_from_db_fields` | DB boundary for Python/backend code; rate is an exact `Decimal`, base/quote are strings |
| per-currency balances | a container with **no scalar accessor** — a multi-currency balance cannot collapse onto one currency |

## Invariants that must hold on every end

1. **No float anywhere in money paths.** Amounts and exchange rates are decimal.
2. **Rounding is `ROUND_HALF_EVEN` at 2 dp** unless an explicit mode is passed.
   (This is the contract point the frontend `decimal.js` default `ROUND_HALF_UP`
   violates today — convergence onto this contract closes the gap.)
3. **No cross-currency arithmetic** without an explicit `convert` and typed
   `ExchangeRate`; a naked Decimal rate is not a conversion boundary.
4. **Currencies are validated ISO-4217**, not bare strings.
5. **Boundary codecs are package-owned.** Wire payloads use decimal strings
   (never JSON numbers); DB adapters expose exact `Decimal` fields only at the
   storage edge. Malformed payloads raise typed money errors.

Conformance to 1–4 (for the deterministic cases) is enforced by the vectors; the
construction-rejection laws are enforced by each stack's own unit tests against
this contract.

## Shared API surface (identifier parity)

The vectors lock *behaviour*; `vectors.json["shared_api"]` locks the *identifier
surface* so the two ends cannot drift in naming/coverage. Every name below MUST
be exported by **both** `apps/backend/src/money` (`__all__`) and
`apps/frontend/src/lib/money` (`index.ts`), enforced by
`tests/tooling/test_money_api_parity.py`:

`Money`, `Currency`, `ExchangeRate`, `convert`, `ISO_4217_CODES`,
`MONEY_QUANTUM`, `MoneyError`, `FloatNotAllowedError`,
`InvalidCurrencyError`, `InvalidExchangeRateError`, `CurrencyMismatchError`,
`InvalidMoneyPayloadError`, `money_to_wire`, `money_from_wire`,
`exchange_rate_to_wire`, `exchange_rate_from_wire`.

Intentionally **per-end** (NOT part of the shared surface): backend-only
`to_money`, `CurrencyBalance(s)`, DB field adapters, the `adopt` helpers;
frontend-only display formatters (`formatCurrencyLocale`, …) and the loose Decimal helpers
(`sumAmounts`, …) inherited from the former `lib/currency`.
