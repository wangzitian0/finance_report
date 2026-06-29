# Money conformance vectors — the cross-language financial standard

`vectors.json` is the **single source of truth** for money *behaviour* across
every end of the system (#1167). It is **language-neutral data**, consumed at
**test time only** — it is never shipped into a runtime image.

## The rule

Every money implementation must load `vectors.json` and reproduce **every**
expected value exactly:

| Stack | Implementation | Conformance test |
|-------|----------------|------------------|
| Backend (Python) | `common/money/` (reference) | `tests/tooling/test_money_conformance.py` |
| Frontend (TypeScript) | `apps/frontend/src/lib/money/` | `apps/frontend/src/lib/money/*.conformance.test.ts` |

If Python and TypeScript ever disagree on a rounding boundary, a conversion, or a
currency validation, the conformance test fails on whichever end drifted. This is
what makes "consistent across every end" *provable* rather than aspirational.

## Why data, not shared code

The frontend is TypeScript and cannot import the Python `common/money`. So the
shared artifact is the **standard** (this data + the prose contract in
[`../contract/money.contract.md`](../contract/money.contract.md) and
[`common/money/readme.md#money-type`](../readme.md#money-type)), not a
runtime library. Each stack keeps its own idiomatic implementation in its own
deployable; `common/` stays a dev/test-time toolkit (no `pyproject`, not copied
into any image).

## Vector groups

- **`rounding`** — `amount` quantized to 2 dp under `rounding` ⇒ `expected`.
  Includes the half-to-even cases that distinguish banker's rounding from
  HALF_UP (the real FE/BE divergence this standard closes).
- **`convert`** — `amount` in `from` × typed `ExchangeRate(from, to, rate)` under
  `rounding` ⇒ `expected` (the single FX primitive).
- **`currency_normalize`** — `input` ⇒ canonical ISO-4217 `expected`.
- **`currency_invalid`** — codes that MUST be rejected.

All amounts/rates are decimal **strings** (never JSON floats), per the decimal
red line. Runtime conversion uses the typed `ExchangeRate` wrapper; the vector
keeps `from`, `to`, and `rate` separate so every stack constructs the same
directed rate.
