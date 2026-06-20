# UnitPrice module contract (language-neutral interface)

> The **interface** half of the unit-price module's SSOT; the conformance half
> is [`../conformance/vectors.json`](../conformance/vectors.json). Authoritative
> prose: [`docs/ssot/base-packages.md`](../../../docs/ssot/base-packages.md).

## Types

- **`UnitPrice`** — an immutable `(rate, currency, unit)` triple: *money per one
  unit of a quantity* (share price, unit cost, per-contract rate).
  - `rate` is Decimal-backed. **`float`/`bool` are rejected** at construction.
  - `currency` is a `Currency` (from `money`); `unit` is a `Unit` (from
    `quantity`). Both are normalized at construction.
  - The exact rate is stored; rounding happens only via `quantize()`.

## Operations & Laws

| Operation | Law |
|-----------|-----|
| construct `UnitPrice(rate, currency, unit)` | rejects float/bool; normalizes currency + unit; immutable |
| `zero(currency, unit)` / `is_zero()` | typed zero construction and predicate |
| `quantize(rounding)` | **6 dp; default `ROUND_HALF_UP`** — the price/unit-rate quantum, NOT the 2-dp money quantum |
| `unit_price * quantity` → `Money` | extends a quantity at this price; **unit must match** (else typed error); amount is exact/unquantized — quantize at the money boundary. Written price-first: `Quantity` rejects non-scalar right-multiplication to protect the float red line |
| `from_total(money, quantity)` → `UnitPrice` | `Money / Quantity`; keeps the money's currency and the quantity's unit; **zero quantity is undefined** (raises) |
| `neg` / `abs` | keeps currency + unit |
| `compare` | **same currency AND same unit only**; otherwise typed error |
| `unit_price_to_wire` / `unit_price_from_wire` | JSON boundary; rate is a decimal string, currency/unit are string codes; JSON numbers rejected |
| `unit_price_to_db_fields` / `unit_price_from_db_fields` | DB boundary for Python/backend code; rate is an exact `Decimal`, currency/unit are strings |

## Invariants

1. **No float** in unit-price paths.
2. **Unit-price quantization is 6 dp / `ROUND_HALF_UP`** unless an explicit mode
   is passed — distinct from the 2-dp money quantum.
3. **A unit price applies to a quantity only when units agree**, and the product
   is `Money` in the price's currency, never a naked `Decimal`.
4. **No cross-currency / cross-unit comparison** of unit prices.
5. **Boundary codecs are package-owned.** Wire payloads use decimal strings
   (never JSON numbers); DB adapters expose exact `Decimal` rates only at the
   storage edge. Malformed payloads raise typed unit-price errors.

## Shared API Surface

`vectors.json["shared_api"]` is exported by `apps/backend/src/unit_price`
(`__all__`), enforced by `tests/tooling/test_unit_price_api_parity.py`:

`UnitPrice`, `UNIT_PRICE_QUANTUM`, `UNIT_PRICE_DP`, `UNIT_PRICE_ROUNDING`,
`UnitPriceError`, `FloatNotAllowedError`, `CurrencyMismatchError`,
`UnitMismatchError`, `UndefinedUnitPriceError`, `InvalidUnitPricePayloadError`,
`unit_price_to_wire`, `unit_price_from_wire`.

A TypeScript frontend implementation is a **P2 follow-up** (#1253): there are no
frontend unit-price call sites today, and frontend display helpers (nullable /
signed price display) are explicitly P2 in the issue. The conformance vectors are
already language-neutral so frontend adoption is purely additive.
