// Typed money errors — the TS mirror of common/money/errors.py / src.money.errors,
// so the frontend and backend expose the same money error surface (#1167).
// Callers can catch MoneyError for any money-domain violation, or the subtype.

export class MoneyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MoneyError";
  }
}

/** A float (JS number) / non-finite value was supplied where a Decimal is required. */
export class FloatNotAllowedError extends MoneyError {
  constructor(message: string) {
    super(message);
    this.name = "FloatNotAllowedError";
  }
}

/** A currency code is not a recognised ISO-4217 alphabetic code. */
export class InvalidCurrencyError extends MoneyError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidCurrencyError";
  }
}

/** An operation combined two different currencies without conversion. */
export class CurrencyMismatchError extends MoneyError {
  constructor(message: string) {
    super(message);
    this.name = "CurrencyMismatchError";
  }
}

/** An exchange rate is zero, negative, non-finite, or otherwise invalid. */
export class InvalidExchangeRateError extends MoneyError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidExchangeRateError";
  }
}
