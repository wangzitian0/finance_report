// Money — the TS rendering of the shared money contract
// (common/money/contract/money.contract.md). Immutable, Decimal-backed; rejects
// non-finite/float-ish input; same-currency arithmetic only; banker's rounding
// (ROUND_HALF_EVEN) at the 2-dp boundary — matching the Python reference impl.
// Conformance to the standard is proven by money.conformance.test.ts.

import Decimal from "decimal.js";

import { Currency } from "./currency";
import { CurrencyMismatchError, FloatNotAllowedError, InvalidExchangeRateError } from "./errors";

export { CurrencyMismatchError };

export type RoundingName = "ROUND_HALF_EVEN" | "ROUND_HALF_UP";

const ROUNDING: Record<RoundingName, Decimal.Rounding> = {
  ROUND_HALF_EVEN: Decimal.ROUND_HALF_EVEN,
  ROUND_HALF_UP: Decimal.ROUND_HALF_UP,
};

export const MONEY_DP = 2;
// Aligned with the backend `MONEY_QUANTUM` (Decimal("0.01")) so both ends expose
// the same canonical money quantum identifier (the API-parity guard checks this).
export const MONEY_QUANTUM = new Decimal("0.01");
export const DEFAULT_ROUNDING: RoundingName = "ROUND_HALF_EVEN";

/** Amount input: a Decimal or a decimal STRING. Never a JS number (float). */
export type AmountInput = Decimal | string;

function coerceDecimal(value: Decimal | string, what: string): Decimal {
  let d: Decimal;
  if (value instanceof Decimal) {
    d = value;
  } else if (typeof value === "string") {
    d = new Decimal(value);
  } else {
    // Deliberately reject `number` (and anything else) — JS numbers are IEEE-754 floats.
    throw new FloatNotAllowedError(`${what} must be a Decimal or decimal string, not a number`);
  }
  if (!d.isFinite()) throw new FloatNotAllowedError(`${what} must be finite`);
  return d;
}

function coerceAmount(value: AmountInput): Decimal {
  return coerceDecimal(value, "Money amount");
}

/** An immutable amount in a single currency. */
export class Money {
  readonly amount: Decimal;
  readonly currency: Currency;

  constructor(amount: AmountInput, currency: Currency | string) {
    this.amount = coerceAmount(amount);
    this.currency = Currency.of(currency);
    Object.freeze(this);
  }

  static zero(currency: Currency | string): Money {
    return new Money("0", currency);
  }

  /** Round to the canonical 2-dp money quantum (banker's rounding by default). */
  quantize(rounding: RoundingName = DEFAULT_ROUNDING): Money {
    return new Money(this.amount.toDecimalPlaces(MONEY_DP, ROUNDING[rounding]), this.currency);
  }

  private requireSameCurrency(other: Money, op: string): void {
    if (!this.currency.equals(other.currency)) {
      throw new CurrencyMismatchError(
        `cannot ${op} across currencies: ${this.currency.code} and ${other.currency.code} — use convert()`,
      );
    }
  }

  add(other: Money): Money {
    this.requireSameCurrency(other, "add");
    return new Money(this.amount.plus(other.amount), this.currency);
  }

  subtract(other: Money): Money {
    this.requireSameCurrency(other, "subtract");
    return new Money(this.amount.minus(other.amount), this.currency);
  }

  equals(other: Money): boolean {
    return this.currency.equals(other.currency) && this.amount.equals(other.amount);
  }

  /** Same-currency ordering: -1 | 0 | 1. Cross-currency throws (no implicit FX). */
  compareTo(other: Money): number {
    this.requireSameCurrency(other, "compare");
    return this.amount.comparedTo(other.amount);
  }

  lessThan(other: Money): boolean {
    return this.compareTo(other) < 0;
  }

  lessThanOrEqual(other: Money): boolean {
    return this.compareTo(other) <= 0;
  }

  greaterThan(other: Money): boolean {
    return this.compareTo(other) > 0;
  }

  greaterThanOrEqual(other: Money): boolean {
    return this.compareTo(other) >= 0;
  }

  toString(): string {
    return `${this.amount.toString()} ${this.currency.code}`;
  }
}

/** A directed FX rate: amount_quote = amount_base * rate. */
export class ExchangeRate {
  readonly base: Currency;
  readonly quote: Currency;
  readonly rate: Decimal;

  constructor(base: Currency | string, quote: Currency | string, rate: AmountInput) {
    this.base = Currency.of(base);
    this.quote = Currency.of(quote);
    this.rate = coerceDecimal(rate, "FX rate");
    if (this.rate.lessThanOrEqualTo(0)) {
      throw new InvalidExchangeRateError("FX rate must be finite and positive");
    }
    Object.freeze(this);
  }

  inverse(): ExchangeRate {
    return new ExchangeRate(this.quote, this.base, new Decimal(1).dividedBy(this.rate));
  }

  toString(): string {
    return `${this.base.code}/${this.quote.code} ${this.rate.toString()}`;
  }
}

/** The single FX conversion primitive: typed directed rate, 2-dp rounding. */
export function convert(money: Money, rate: ExchangeRate, rounding: RoundingName = DEFAULT_ROUNDING): Money {
  if (!(rate instanceof ExchangeRate)) {
    throw new FloatNotAllowedError(`convert rate must be ExchangeRate`);
  }
  if (!money.currency.equals(rate.base)) {
    throw new CurrencyMismatchError(`cannot convert ${money.currency.code} with ${rate.base.code}/${rate.quote.code} rate`);
  }
  return new Money(money.amount.times(rate.rate), rate.quote).quantize(rounding);
}
