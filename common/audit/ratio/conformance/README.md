# Ratio conformance vectors — the cross-language percent standard

`vectors.json` is the **single source of truth** for ratio/percent *behaviour*
across every end (#1167 base-package family). Language-neutral data, consumed at
**test time only** — never shipped into a runtime image.

## The rule

Every ratio implementation loads `vectors.json` and must reproduce **every**
expected value:

| Stack | Implementation | Conformance test |
|-------|----------------|------------------|
| Backend (Python) | `common/audit/ratio` (reference) / `apps/backend/src/audit/ratio` | `tests/tooling/test_ratio_conformance.py` |
| Frontend (TypeScript) | `apps/frontend/src/lib/audit/ratio` | `apps/frontend/src/lib/audit/ratio/ratio.conformance.test.ts` |

The canonical percent-display policy is **2 dp, ROUND_HALF_UP** — the finance
display convention, deliberately distinct from money's banker's rounding
(percentages are not money). The vectors include half-up boundary cases so a
stack that defaulted to HALF_EVEN fails immediately.

## Vector groups
- **`to_percent`** — `ratio` → percentage number at `dp`, HALF_UP.
- **`percent_of`** — `part / whole` → percentage at `dp` (the `fraction(...).to_percent(...)` path).
- **`from_percent`** — percentage number → ratio, round-trips back to the same percent.
