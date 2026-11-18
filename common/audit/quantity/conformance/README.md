# Quantity conformance vectors — the cross-language quantity standard
`vectors.json` is the **single source of truth** for quantity behaviour across every end (#1167). It is language-neutral data, consumed at **test time only**.
## The Rule
Every quantity implementation loads `vectors.json` and must reproduce every expected value: | Stack | Implementation | Conformance test |
|-------|----------------|------------------|
| Backend runtime | `apps/backend/src/audit/quantity` | _(Python vector runner retired in #3115)_ | | Frontend | `apps/frontend/src/lib/audit/quantity` | `apps/frontend/src/lib/audit/quantity/quantity.conformance.test.ts` | The canonical quantity policy is **6 dp, ROUND_HALF_UP**. Unit strings are
normalized and same-unit arithmetic is enforced; a quantity ratio derives a `Ratio`.
## Vector Groups
- **`unit_normalize`** — accepted unit strings and their canonical form. - **`unit_invalid`** — unit strings that must be rejected. - **`quantize`** — `Quantity(value, unit).quantize()` expected values. - **`ratio`** — same-unit quantity ratios and percent display expectations.
