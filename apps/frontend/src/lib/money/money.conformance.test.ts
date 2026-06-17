// Frontend side of the cross-language money conformance suite (#1167).
//
// Proves the frontend rendering of the money standard: AC2.19.1 (Currency
// validation), AC2.20.1 (rounding + convert), AC2.21.1 (the value-type laws).
// These are the same ACs the Python reference impl proves in tests/tooling; here
// they are asserted against the SAME language-neutral standard the backend uses
// (common/money/conformance/vectors.json), so the frontend cannot drift from the
// backend on a rounding boundary, a conversion, a currency validation, or the
// ISO-4217 set. See common/money/conformance/README.md.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

import { Currency, FloatNotAllowedError, InvalidCurrencyError, ISO_4217_CODES } from "./index";
import { Money, convert, type RoundingName } from "./money";

const here = dirname(fileURLToPath(import.meta.url));
const vectorsPath = resolve(here, "../../../../../common/money/conformance/vectors.json");
const VECTORS = JSON.parse(readFileSync(vectorsPath, "utf-8")) as {
  money_quantum: string;
  default_rounding: string;
  iso4217: string[];
  rounding: { amount: string; rounding: RoundingName; expected: string }[];
  convert: { amount: string; from: string; rate: string; to: string; rounding: RoundingName; expected: string }[];
  currency_normalize: { input: string; expected: string }[];
  currency_invalid: string[];
};

describe("money conformance (cross-language standard #1167)", () => {
  it("declares the same quantum and default rounding", () => {
    expect(VECTORS.money_quantum).toBe("0.01");
    expect(VECTORS.default_rounding).toBe("ROUND_HALF_EVEN");
  });

  it("matches every rounding vector (banker's rounding, not HALF_UP)", () => {
    for (const c of VECTORS.rounding) {
      const got = new Money(c.amount, "USD").quantize(c.rounding).amount;
      expect(got.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
    }
  });

  it("matches every convert vector", () => {
    for (const c of VECTORS.convert) {
      const result = convert(new Money(c.amount, c.from), c.rate, c.to, c.rounding);
      expect(result.amount.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
      expect(result.currency.code).toBe(c.to);
    }
  });

  it("normalizes and rejects currencies per the standard", () => {
    for (const c of VECTORS.currency_normalize) {
      expect(new Currency(c.input).code).toBe(c.expected);
    }
    for (const bad of VECTORS.currency_invalid) {
      expect(() => new Currency(bad)).toThrow(InvalidCurrencyError);
    }
  });

  it("embeds exactly the canonical ISO-4217 set", () => {
    expect([...ISO_4217_CODES].sort()).toEqual([...VECTORS.iso4217].sort());
  });
});

describe("money value-type laws (TS rendering of the contract)", () => {
  it("rejects float (JS number) amounts and rates", () => {
    // @ts-expect-error number is intentionally not assignable to AmountInput
    expect(() => new Money(10.0, "USD")).toThrow(FloatNotAllowedError);
    // @ts-expect-error number rate is rejected
    expect(() => convert(new Money("1.00", "USD"), 1.2, "EUR")).toThrow(FloatNotAllowedError);
  });

  it("is same-currency only for arithmetic and comparison", () => {
    const usd = new Money("10.00", "USD");
    const sgd = new Money("10.00", "SGD");
    expect(usd.add(new Money("5", "USD")).amount.equals(new Decimal("15"))).toBe(true);
    expect(() => usd.add(sgd)).toThrow();
    expect(usd.equals(sgd)).toBe(false);

    const a = new Money("1", "USD");
    const b = new Money("2", "USD");
    expect(a.lessThan(b)).toBe(true);
    expect(b.greaterThanOrEqual(a)).toBe(true);
    expect(a.compareTo(b)).toBe(-1);
    expect(() => a.lessThan(sgd)).toThrow(); // cross-currency compare throws
  });

  it("rejects non-finite Decimal amounts and rates", () => {
    expect(() => new Money(new Decimal(Infinity), "USD")).toThrow(FloatNotAllowedError);
    expect(() => convert(new Money("1.00", "USD"), new Decimal(Infinity), "EUR")).toThrow(FloatNotAllowedError);
  });
});
