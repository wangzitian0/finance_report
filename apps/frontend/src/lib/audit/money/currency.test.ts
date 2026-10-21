// Currency boundary checks that the conformance vectors do not cover (#2594).
// Wire data is untyped at runtime, so a missing or numeric currency code can
// reach normalizeCurrency even though its TypeScript signature says string.

import { describe, expect, it } from "vitest";

import { Currency, InvalidCurrencyError, normalizeCurrency } from "./currency";

describe("Currency", () => {
  it.each([null, undefined, 702])(
    "AC-audit.19.1 rejects the non-string wire value %s with InvalidCurrencyError",
    (value) => {
      const read = () => normalizeCurrency(value as unknown as string);

      expect(read).toThrow(InvalidCurrencyError);
      expect(read).toThrow("currency code must be a string");
      expect(() => new Currency(value as unknown as string)).toThrow(
        InvalidCurrencyError,
      );
    },
  );

  it("AC-audit.19.1 renders as its normalized ISO-4217 code in string contexts", () => {
    const currency = new Currency(" sgd ");

    expect(String(currency)).toBe("SGD");
    expect(`${currency}`).toBe("SGD");
    expect(Currency.of(currency)).toBe(currency);
  });
});
