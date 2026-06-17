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

function coerceAmount(value: AmountInput): Decimal {
  if (value instanceof Decimal) return value;
  if (typeof value === "string") {
    const d = new Decimal(value);
    if (!d.isFinite()) throw new TypeError("Money amount must be finite");
    return d;
  }
  // Deliberately reject `number` — JS numbers are IEEE-754 floats.
  throw new TypeError("Money amount must be a Decimal or decimal string, not a number");
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
  if (typeof rate === "number") {
    throw new TypeError("FX rate must be a Decimal or decimal string, not a number");
  }
  const r = rate instanceof Decimal ? rate : new Decimal(rate);
  return new Money(money.amount.times(r), to).quantize(rounding);
}
