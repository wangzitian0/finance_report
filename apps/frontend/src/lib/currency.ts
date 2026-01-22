import Decimal from "decimal.js";

export function parseAmount(value: string | number): Decimal {
  if (value === null || value === undefined) {
    throw new Error("parseAmount received null or undefined");
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") {
      throw new Error("parseAmount received an empty string");
    }
    return new Decimal(trimmed);
  }

  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("parseAmount received a non-finite number");
    }
    return new Decimal(value);
  }

  throw new Error("parseAmount received an invalid type");
}

export function formatAmount(value: Decimal | string | number, decimals = 2): string {
  return new Decimal(value).toFixed(decimals);
}

export function sumAmounts(amounts: (Decimal | string | number)[]): Decimal {
  return amounts.reduce<Decimal>((sum, val) => sum.add(new Decimal(val)), new Decimal(0));
}

export function subtractAmounts(a: Decimal | string | number, b: Decimal | string | number): Decimal {
  return new Decimal(a).minus(b);
}

export function multiplyAmount(a: Decimal | string | number, b: Decimal | string | number): Decimal {
  return new Decimal(a).times(b);
}

export function divideAmount(a: Decimal | string | number, b: Decimal | string | number): Decimal {
  return new Decimal(a).div(b);
}

export function compareAmounts(a: Decimal | string | number, b: Decimal | string | number): number {
  return new Decimal(a).comparedTo(b);
}

export function isAmountZero(value: Decimal | string | number, tolerance = 0.01): boolean {
  return new Decimal(value).abs().lessThanOrEqualTo(tolerance);
}

export function formatCurrency(
  value: Decimal | string | number,
  currency: string = "SGD",
  decimals = 2
): string {
  const amount = formatAmount(value, decimals);
  return `${currency} ${amount}`;
}

export function formatCurrencyLocale(
  value: Decimal | string | number,
  currency: string = "SGD",
  locale: string = "en-US",
  options?: Intl.NumberFormatOptions
): string {
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    ...options,
  });
  return formatter.format(Number(value));
}
