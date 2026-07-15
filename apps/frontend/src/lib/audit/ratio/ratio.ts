// Ratio — the TS rendering of the shared ratio/percent contract
// (common/audit/ratio/contract/ratio.contract.md). Dimensionless, Decimal-backed;
// rejects float; ONE percent-display policy (2 dp, ROUND_HALF_UP) matching the
// Python reference. Conformance proven by ratio.conformance.test.ts.

import Decimal from "decimal.js";

import { decimalStringFromWire as sharedDecimalStringFromWire, decimalToWire } from "@/lib/audit/wire";

import { FloatNotAllowedError, InvalidRatioPayloadError, UndefinedRatioError } from "./errors";

export const PERCENT_DP = 2;
// Canonical percent-display rounding — finance convention, deliberately NOT
// money's HALF_EVEN (a percentage is not a currency amount).
export const PERCENT_ROUNDING: Decimal.Rounding = Decimal.ROUND_HALF_UP;

/** Ratio input: a Decimal or a decimal STRING. Never a JS number (float). */
export type RatioInput = Decimal | string;
export type RatioWire = string;

function coerce(value: RatioInput, what = "ratio value"): Decimal {
  if (value instanceof Decimal) return value;
  if (typeof value === "string") return new Decimal(value);
  // Deliberately reject `number` (and anything else) — JS numbers are floats.
  throw new FloatNotAllowedError(`${what} must be a Decimal or decimal string, not a number`);
}

function decimalStringFromWire(value: unknown, what = "ratio value"): string {
  return sharedDecimalStringFromWire(value, what, FloatNotAllowedError, InvalidRatioPayloadError);
}

/** An immutable dimensionless ratio (`0.125` == 12.5%). */
export class Ratio {
  readonly value: Decimal;

  constructor(value: RatioInput) {
    this.value = coerce(value);
    Object.freeze(this);
  }

  /** Build a ratio `part / whole`. A zero whole is undefined and raises. */
  static fraction(part: RatioInput, whole: RatioInput): Ratio {
    const p = coerce(part, "part");
    const w = coerce(whole, "whole");
    if (w.isZero()) throw new UndefinedRatioError("ratio is undefined for a zero whole");
    return new Ratio(p.dividedBy(w));
  }

  static zero(): Ratio {
    return new Ratio("0");
  }

  isZero(): boolean {
    return this.value.isZero();
  }

  /** Build a ratio from a percentage number (`12.5` -> `0.125`). */
  static fromPercent(percent: RatioInput): Ratio {
    return new Ratio(coerce(percent, "percent").dividedBy(100));
  }

  /** Percentage value quantized to `dp` (default 2 dp, HALF_UP). */
  toPercent(dp: number = PERCENT_DP, rounding: Decimal.Rounding = PERCENT_ROUNDING): Decimal {
    return this.value.times(100).toDecimalPlaces(dp, rounding);
  }

  /** Render as a `"12.50%"` string at the canonical policy. */
  formatPercent(dp: number = PERCENT_DP): string {
    return `${this.toPercent(dp).toFixed(dp)}%`;
  }

  add(other: Ratio): Ratio {
    return new Ratio(this.value.plus(other.value));
  }

  subtract(other: Ratio): Ratio {
    return new Ratio(this.value.minus(other.value));
  }

  compareTo(other: Ratio): number {
    return this.value.comparedTo(other.value);
  }

  equals(other: Ratio): boolean {
    return this.value.equals(other.value);
  }

  toString(): string {
    return this.formatPercent();
  }
}

export function ratio_to_wire(ratio: Ratio): RatioWire {
  if (!(ratio instanceof Ratio)) {
    throw new TypeError("ratio_to_wire expects Ratio");
  }
  return decimalToWire(ratio.value);
}

export function ratio_from_wire(value: unknown): Ratio {
  return new Ratio(decimalStringFromWire(value));
}
