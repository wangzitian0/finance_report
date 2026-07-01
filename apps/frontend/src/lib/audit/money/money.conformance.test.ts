// Frontend side of the cross-language money conformance suite (#1167).
//
// Proves the frontend rendering of the money standard: AC2.19.1 (Currency
// validation), AC2.20.1 (rounding + convert), AC2.21.1 (the value-type laws).
// These are the same ACs the Python reference impl proves in tests/tooling; here
// they are asserted against the SAME language-neutral standard the backend uses
// (common/audit/money/conformance/vectors.json), so the frontend cannot drift from the
// backend on a rounding boundary, a conversion, a currency validation, or the
// ISO-4217 set. See common/audit/money/conformance/README.md.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

import {
  Currency,
  CurrencyMismatchError,
  ExchangeRate,
  FloatNotAllowedError,
  InvalidCurrencyError,
  ISO_4217_CODES,
} from "./index";
import { Money, convert, type RoundingName } from "./money";

const here = dirname(fileURLToPath(import.meta.url));
const vectorsPath = resolve(here, "../../../../../../common/audit/money/conformance/vectors.json");
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
  it("AC2.20.1 declares the same quantum and default rounding", () => {
    expect(VECTORS.money_quantum).toBe("0.01");
    expect(VECTORS.default_rounding).toBe("ROUND_HALF_EVEN");
  });

  it("AC2.20.1 matches every rounding vector (banker's rounding, not HALF_UP)", () => {
    for (const c of VECTORS.rounding) {
      const got = new Money(c.amount, "USD").quantize(c.rounding).amount;
      expect(got.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
    }
  });

  it("AC12.30.3 matches every convert vector through ExchangeRate", () => {
    for (const c of VECTORS.convert) {
      const result = convert(new Money(c.amount, c.from), new ExchangeRate(c.from, c.to, c.rate), c.rounding);
      expect(result.amount.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
      expect(result.currency.code).toBe(c.to);
    }
  });

  it("AC2.19.1 normalizes and rejects currencies per the standard", () => {
    for (const c of VECTORS.currency_normalize) {
      expect(new Currency(c.input).code).toBe(c.expected);
    }
    for (const bad of VECTORS.currency_invalid) {
      expect(() => new Currency(bad)).toThrow(InvalidCurrencyError);
    }
  });

  it("AC2.19.1 embeds exactly the canonical ISO-4217 set", () => {
    expect([...ISO_4217_CODES].sort()).toEqual([...VECTORS.iso4217].sort());
  });
});

describe("money value-type laws (TS rendering of the contract)", () => {
  it("AC2.19.1 AC12.30.3 rejects float (JS number) amounts and rates", () => {
    // @ts-expect-error number is intentionally not assignable to AmountInput
    expect(() => new Money(10.0, "USD")).toThrow(FloatNotAllowedError);
    // @ts-expect-error number rate is rejected
    expect(() => new ExchangeRate("USD", "EUR", 1.2)).toThrow(FloatNotAllowedError);
  });

  it("AC2.19.2 is same-currency only for arithmetic and comparison", () => {
    const usd = new Money("10.00", "USD");
    const sgd = new Money("10.00", "SGD");
    expect(Money.zero("USD").equals(new Money("0", "USD"))).toBe(true);
    expect(usd.add(new Money("5", "USD")).amount.equals(new Decimal("15"))).toBe(true);
    expect(usd.subtract(new Money("2", "USD")).amount.equals(new Decimal("8"))).toBe(true);
    expect(() => usd.add(sgd)).toThrow();
    expect(usd.equals(sgd)).toBe(false);

    const a = new Money("1", "USD");
    const b = new Money("2", "USD");
    expect(a.lessThan(b)).toBe(true);
    expect(a.lessThanOrEqual(b)).toBe(true);
    expect(b.greaterThan(a)).toBe(true);
    expect(b.greaterThanOrEqual(a)).toBe(true);
    expect(a.compareTo(b)).toBe(-1);
    expect(String(a)).toBe("1 USD");
    expect(() => a.lessThan(sgd)).toThrow(); // cross-currency compare throws
  });

  it("AC2.19.1 AC12.30.3 rejects non-finite Decimal amounts and rates", () => {
    expect(() => new Money(new Decimal(Infinity), "USD")).toThrow(FloatNotAllowedError);
    expect(() => new ExchangeRate("USD", "EUR", new Decimal(Infinity))).toThrow(FloatNotAllowedError);
  });

  it("AC12.30.3 uses ExchangeRate as the typed conversion boundary", () => {
    const rate = new ExchangeRate("usd", "sgd", "1.35");
    expect(rate.base.code).toBe("USD");
    expect(rate.quote.code).toBe("SGD");
    expect(String(rate)).toBe("USD/SGD 1.35");
    expect(convert(new Money("100.00", "USD"), rate).equals(new Money("135.00", "SGD"))).toBe(true);
    expect(convert(new Money("135.00", "SGD"), rate.inverse()).equals(new Money("100.00", "USD"))).toBe(true);
    expect(() => convert(new Money("100.00", "EUR"), rate)).toThrow(CurrencyMismatchError);
    expect(() => new ExchangeRate("USD", "SGD", "0")).toThrow();
    // @ts-expect-error convert rejects non-ExchangeRate objects at runtime too
    expect(() => convert(new Money("100.00", "USD"), "1.35")).toThrow(FloatNotAllowedError);
  });
});
