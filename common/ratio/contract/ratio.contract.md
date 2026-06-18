# Ratio module contract (language-neutral interface)

> The **interface** half of the ratio module's SSOT; the **conformance** half is
> [`../conformance/vectors.json`](../conformance/vectors.json). Second instance of
> the base-package template — see [`docs/ssot/base-packages.md`](../../../docs/ssot/base-packages.md).

## Type

- **`Ratio`** — an immutable, `Decimal`-backed **dimensionless** ratio
  (`0.125` == 12.5%). Construction **rejects `float`/`bool`**. Stores the exact
  `Decimal`; rounding happens only at the percent boundary.

## Operations & laws

| Operation | Law |
|-----------|-----|
| construct `Ratio(value)` | rejects float; immutable |
| `fraction(part, whole)` | the single primitive to build from two quantities; **zero whole is undefined → raises** |
| `from_percent(p)` | `p / 100` |
| `to_percent(dp=2, rounding=HALF_UP)` | percentage value quantized to `dp` with the canonical policy |
| `format_percent(dp=2)` | `"12.50%"` string |
| `is_zero()` / `isZero()` | typed zero predicate; call-sites should not compare `Ratio` to naked numeric zero |
| `add`/`sub`/`compare`/`neg`/`*scalar` | dimensionless arithmetic (ratios share one implicit unit) |

## Invariants (every end)

1. **No float** in ratio paths — values are `Decimal`.
2. **Percent display is `ROUND_HALF_UP` at 2 dp** unless an explicit `dp`/mode is
   passed. This is the one project-wide percent policy; it is intentionally NOT
   money's `ROUND_HALF_EVEN` (a percentage is not a currency amount).
3. **Zero whole is undefined** — `fraction(x, 0)` raises, never silently 0.
4. **Typed zero checks** — compare ratio values with `Ratio`/`is_zero`, not with
   `0`, `0.0`, or raw `Decimal("0")` at call-sites.

## Shared API surface (identifier parity)

`vectors.json["shared_api"]` — exported by **both** `apps/backend/src/ratio`
(`__all__`) and `apps/frontend/src/lib/ratio` (`index.ts`), enforced by
`tests/tooling/test_ratio_api_parity.py`:
`Ratio`, `RatioError`, `FloatNotAllowedError`, `PERCENT_DP`, `PERCENT_ROUNDING`.
