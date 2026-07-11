# Quantity module contract (language-neutral interface)

> The **interface** half of the quantity module's SSOT; the conformance half is
> [`../conformance/vectors.json`](../conformance/vectors.json). Authoritative
> prose: [`common/audit/readme.md#base-packages`](../../readme.md#base-packages).

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
| `quantity_to_wire` / `quantity_from_wire` | JSON boundary; value is a decimal string and unit is a string; JSON numbers are rejected |
| `quantity_to_db_fields` / `quantity_from_db_fields` | DB boundary for Python/backend code; value is an exact `Decimal`, unit is a string |

## Invariants

1. **No float** in quantity paths.
2. **Quantity quantization is 6 dp / `ROUND_HALF_UP`** unless an explicit mode is
   passed.
3. **No cross-unit arithmetic** without an explicit future conversion table.
4. **Quantity ratios are `Ratio`**, not naked Decimal division.
5. **Boundary codecs are package-owned.** Wire payloads use decimal strings
   (never JSON numbers); DB adapters expose exact `Decimal` values only at the
   storage edge. Malformed payloads raise typed quantity errors.

## Shared API Surface

`vectors.json["shared_api"]` is exported by both `apps/backend/src/audit/quantity`
(`__all__`) and `apps/frontend/src/lib/audit/quantity` (`index.ts`), enforced by
`tests/tooling/test_quantity_api_parity.py`:

`Quantity`, `Unit`, `QUANTITY_QUANTUM`, `QUANTITY_DP`, `QUANTITY_ROUNDING`,
`QuantityError`, `FloatNotAllowedError`, `InvalidQuantityPayloadError`,
`InvalidUnitError`, `UnitMismatchError`, `quantity_to_wire`,
`quantity_from_wire`.
