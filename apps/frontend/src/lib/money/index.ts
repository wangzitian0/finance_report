// The frontend money module — the TS implementation of the shared, cross-language
// money standard (#1167). Contract: common/money/contract/money.contract.md.
// Proven consistent with the Python reference impl via the shared conformance
// vectors (common/money/conformance/vectors.json), see money.conformance.test.ts.

// Typed error hierarchy — mirrors common/money/errors.py / src.money.errors so
// the frontend and backend expose the same money error surface (API-parity guard).
export {
  MoneyError,
  FloatNotAllowedError,
  InvalidCurrencyError,
  InvalidExchangeRateError,
  InvalidMoneyPayloadError,
  CurrencyMismatchError,
} from "./errors";
export { Currency, normalizeCurrency } from "./currency";
export { ISO_4217_CODES } from "./iso4217";
export {
  Money,
  ExchangeRate,
  convert,
  MONEY_QUANTUM,
  MONEY_DP,
  DEFAULT_ROUNDING,
  exchange_rate_from_wire,
  exchange_rate_to_wire,
  money_from_wire,
  money_to_wire,
  type AmountInput,
  type ExchangeRateWire,
  type MoneyWire,
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
  sumAmounts,
  subtractAmounts,
  multiplyAmount,
  divideAmount,
  compareAmounts,
  isAmountZero,
  formatCurrency,
  formatCurrencyLocale,
} from "./format";
