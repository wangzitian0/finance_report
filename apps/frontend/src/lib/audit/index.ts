// `@/lib/audit` — the number-governor's flat value-object surface.
//
// Re-exports the Shared-Kernel value-object classes that have a frontend mirror
// flat at the package root, so a consumer that only needs the class can write
// `import { Money } from "@/lib/audit"`. Errors, wire codecs, and format helpers
// are NOT re-exported here (several names collide across domains, e.g.
// `FloatNotAllowedError` is defined independently in every domain) — reach those
// via the domain submodule instead: `import { FloatNotAllowedError } from
// "@/lib/audit/money"`. `MoneyTolerance` / `CurrencyBalance(s)` / `UnitPrice` have
// no frontend mirror yet (backend-only / P2 follow-up).
export { Money, Currency, ExchangeRate } from "./money";
export { Ratio } from "./ratio";
export { Quantity, Unit } from "./quantity";
