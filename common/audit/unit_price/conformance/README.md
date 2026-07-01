# Unit-price conformance vectors — the cross-language unit-price standard

`vectors.json` is the **single source of truth** for unit-price behaviour across
every end (EPIC-012 AC12.32). It is language-neutral data, consumed at **test
time only**.

## The Rule

Every unit-price implementation loads `vectors.json` and must reproduce every
expected value:

| Stack | Implementation | Conformance test |
|-------|----------------|------------------|
| Python reference | `common/audit/unit_price` | `tests/tooling/test_unit_price_conformance.py` |
| Backend runtime | `apps/backend/src/audit/unit_price` | `apps/backend/tests/audit/unit_price/test_unit_price_backend.py` |
| Frontend | _(P2 follow-up — display helpers, see #1253)_ | _(pending)_ |

The canonical unit-price policy is **6 dp, ROUND_HALF_UP** (the price/unit-rate
quantum, deliberately **not** the 2-dp money quantum). A unit price carries both
a `Currency` and a `Unit`; applying it to a quantity yields `Money` only when the
units agree.

## Vector Groups

- **`quantize`** — `UnitPrice(rate, currency, unit).quantize()` expected rates.
- **`product`** — `unit_price * quantity` expected (exact, unquantized) money
  amounts.
- **`from_total`** — `UnitPrice.from_total(money, quantity).quantize()` expected
  6-dp rates (`Money / Quantity`).
- **`from_total_undefined`** — zero-quantity totals that must raise.
- **`unit_mismatch`** — quantity/price unit mismatches that must raise.
