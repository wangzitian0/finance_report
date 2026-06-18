# Quantity module contract (language-neutral interface)

> The **interface** half of the quantity module's SSOT; the conformance half is
> [`../conformance/vectors.json`](../conformance/vectors.json). Authoritative
> prose: [`docs/ssot/base-packages.md`](../../../docs/ssot/base-packages.md).

## Types

- **`Unit`** — a normalized quantity unit such as `shares`, `units`, or
  `contracts`.
  - Normalizes input (`strip` + lower-case).
  - Rejects empty, spaced, slash-delimited, or digit-prefixed unit strings.
- **`Quantity`** — an immutable `(value, unit)` pair.
  - `value` is Decimal-backed. **`float`/`bool` are rejected** at construction.
  - The exact value is stored; rounding happens only via `quantize()`.

## Operations & Laws

| Operation | Law |
|-----------|-----|
| construct `Quantity(value, unit)` | rejects float/bool; rejects invalid unit; immutable |
| `zero(unit)` / `is_zero()` | typed zero construction and predicate; call-sites should not compare to naked numeric zero |
| `quantize(rounding)` | 6 dp; default `ROUND_HALF_UP` |
| `add` / `subtract` | **same-unit only**; cross-unit ⇒ typed error |
| `compare` | same-unit only; cross-unit ⇒ typed error |
| `neg` / `abs` / `* scalar` | keeps the same unit |
| `ratio_to(whole)` / `Quantity / Quantity` | same-unit quantities derive a `Ratio`; zero whole is undefined through `Ratio.fraction` |

## Invariants

1. **No float** in quantity paths.
2. **Quantity quantization is 6 dp / `ROUND_HALF_UP`** unless an explicit mode is
   passed.
3. **No cross-unit arithmetic** without an explicit future conversion table.
4. **Quantity ratios are `Ratio`**, not naked Decimal division.

## Shared API Surface

`vectors.json["shared_api"]` is exported by both `apps/backend/src/quantity`
(`__all__`) and `apps/frontend/src/lib/quantity` (`index.ts`), enforced by
`tests/tooling/test_quantity_api_parity.py`:

`Quantity`, `Unit`, `QUANTITY_QUANTUM`, `QUANTITY_DP`, `QUANTITY_ROUNDING`,
`QuantityError`, `FloatNotAllowedError`, `InvalidUnitError`,
`UnitMismatchError`.
