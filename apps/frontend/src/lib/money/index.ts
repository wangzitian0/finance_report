// The frontend money module — the TS implementation of the shared, cross-language
// money standard (#1167). Contract: common/money/contract/money.contract.md.
// Proven consistent with the Python reference impl via the shared conformance
// vectors (common/money/conformance/vectors.json), see money.conformance.test.ts.

export { Currency, InvalidCurrencyError, normalizeCurrency } from "./currency";
export { ISO_4217_CODES } from "./iso4217";
export {
  Money,
  convert,
  CurrencyMismatchError,
  MONEY_DP,
  DEFAULT_ROUNDING,
  type AmountInput,
  type RoundingName,
} from "./money";
// Display/formatting + Decimal helpers (consolidated from the former lib/currency.ts,
// #1167). Behaviour-preserving move so the frontend has one money module; display
// formatting keeps its conventional rounding (money *value* rounding lives in the
// value types above and is conformance-locked to the backend's banker's rounding).
export {
  type MonetaryInput,
  parseAmount,
  toDecimal,
  amountToChartNumber,
  formatAmount,
  formatQuantity,
  sumAmounts,
  subtractAmounts,
  multiplyAmount,
  divideAmount,
  compareAmounts,
  isAmountZero,
  formatCurrency,
  formatCurrencyLocale,
} from "./format";
