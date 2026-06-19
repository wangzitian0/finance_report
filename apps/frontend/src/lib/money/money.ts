// Money — the TS rendering of the shared money contract
// (common/money/contract/money.contract.md). Immutable, Decimal-backed; rejects
// non-finite/float-ish input; same-currency arithmetic only; banker's rounding
// (ROUND_HALF_EVEN) at the 2-dp boundary — matching the Python reference impl.
// Conformance to the standard is proven by money.conformance.test.ts.

import Decimal from "decimal.js";

import { Currency } from "./currency";
import {
  CurrencyMismatchError,
  FloatNotAllowedError,
  InvalidExchangeRateError,
  InvalidMoneyPayloadError,
} from "./errors";

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
export type MoneyWire = { amount: string; currency: string };
export type ExchangeRateWire = { base: string; quote: string; rate: string };

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

function decimalToWire(value: Decimal): string {
  return value.isZero() ? "0" : value.toString();
}

function recordFromWire(payload: unknown, what: string): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new InvalidMoneyPayloadError(`${what} payload must be an object`);
  }
  return payload as Record<string, unknown>;
}

function stringField(payload: Record<string, unknown>, key: string, what: string): string {
  const value = payload[key];
  if (typeof value !== "string") {
    throw new InvalidMoneyPayloadError(`${what} payload field ${key} must be a string`);
  }
  return value;
}

function decimalStringFromWire(value: unknown, what: string): string {
  if (typeof value === "number") {
    throw new FloatNotAllowedError(`${what} must be encoded as a decimal string, not a number`);
  }
  if (typeof value !== "string") {
    throw new FloatNotAllowedError(`${what} must be encoded as a decimal string`);
  }
  try {
    const parsed = new Decimal(value);
    if (!parsed.isFinite()) throw new FloatNotAllowedError(`${what} must be finite`);
  } catch (error) {
    if (error instanceof FloatNotAllowedError) throw error;
    throw new InvalidMoneyPayloadError(`${what} is not a valid decimal string`);
  }
  return value;
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

export function money_to_wire(money: Money): MoneyWire {
  if (!(money instanceof Money)) {
    throw new TypeError("money_to_wire expects Money");
  }
  return { amount: decimalToWire(money.amount), currency: money.currency.code };
}

export function money_from_wire(payload: unknown): Money {
  const fields = recordFromWire(payload, "Money");
  return new Money(decimalStringFromWire(fields.amount, "Money amount"), stringField(fields, "currency", "Money"));
}

export function exchange_rate_to_wire(rate: ExchangeRate): ExchangeRateWire {
  if (!(rate instanceof ExchangeRate)) {
    throw new TypeError("exchange_rate_to_wire expects ExchangeRate");
  }
  return {
    base: rate.base.code,
    quote: rate.quote.code,
    rate: decimalToWire(rate.rate),
  };
}

export function exchange_rate_from_wire(payload: unknown): ExchangeRate {
  const fields = recordFromWire(payload, "ExchangeRate");
  return new ExchangeRate(
    stringField(fields, "base", "ExchangeRate"),
    stringField(fields, "quote", "ExchangeRate"),
    decimalStringFromWire(fields.rate, "FX rate"),
  );
}
