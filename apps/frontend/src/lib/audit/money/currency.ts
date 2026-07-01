// Currency — validated ISO-4217 alphabetic code (the TS rendering of the shared
// money contract, common/audit/money/contract/money.contract.md). Mirrors the Python
// reference impl in common/audit/money/currency.py; both ends are kept in lockstep by
// common/audit/money/conformance/vectors.json.

import { InvalidCurrencyError } from "./errors";
import { ISO_4217_CODES } from "./iso4217";

export { InvalidCurrencyError };

/** Normalize (trim + upper-case) and validate an ISO-4217 alphabetic code. */
export function normalizeCurrency(code: string): string {
  if (typeof code !== "string") {
    throw new InvalidCurrencyError(`currency code must be a string`);
  }
  const normalized = code.trim().toUpperCase();
  if (!ISO_4217_CODES.has(normalized)) {
    throw new InvalidCurrencyError(`not an ISO-4217 currency code: ${JSON.stringify(code)}`);
  }
  return normalized;
}

/** An immutable, validated ISO-4217 currency code. */
export class Currency {
  readonly code: string;

  constructor(code: string) {
    this.code = normalizeCurrency(code);
    Object.freeze(this);
  }

  static of(value: Currency | string): Currency {
    return value instanceof Currency ? value : new Currency(value);
  }

  equals(other: Currency): boolean {
    return this.code === other.code;
  }

  toString(): string {
    return this.code;
  }
}
