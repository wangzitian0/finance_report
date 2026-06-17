// Money — the TS rendering of the shared money contract
// (common/money/contract/money.contract.md). Immutable, Decimal-backed; rejects
// non-finite/float-ish input; same-currency arithmetic only; banker's rounding
// (ROUND_HALF_EVEN) at the 2-dp boundary — matching the Python reference impl.
// Conformance to the standard is proven by money.conformance.test.ts.

import Decimal from "decimal.js";

import { Currency } from "./currency";

export class CurrencyMismatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CurrencyMismatchError";
  }
}

export type RoundingName = "ROUND_HALF_EVEN" | "ROUND_HALF_UP";

const ROUNDING: Record<RoundingName, Decimal.Rounding> = {
  ROUND_HALF_EVEN: Decimal.ROUND_HALF_EVEN,
  ROUND_HALF_UP: Decimal.ROUND_HALF_UP,
};

export const MONEY_DP = 2;
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
    throw new TypeError(`${what} must be a Decimal or decimal string, not a number`);
  }
  if (!d.isFinite()) throw new TypeError(`${what} must be finite`);
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

/** The single FX conversion primitive: decimal rate, explicit target, 2-dp rounding. */
export function convert(
  money: Money,
  rate: Decimal | string,
  to: Currency | string,
  rounding: RoundingName = DEFAULT_ROUNDING,
): Money {
  const r = coerceDecimal(rate, "FX rate");
  return new Money(money.amount.times(r), to).quantize(rounding);
}
