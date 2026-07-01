import Decimal from "decimal.js";

export type MonetaryInput = Decimal | string | number;

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

export function toDecimal(value: MonetaryInput): Decimal {
  return new Decimal(value);
}

export function amountToChartNumber(value: MonetaryInput): number {
  const amount = new Decimal(value);
  return amount.isFinite() ? amount.toNumber() : 0;
}

export function formatAmount(value: MonetaryInput, decimals = 2): string {
  return new Decimal(value).toFixed(decimals);
}

export function sumAmounts(amounts: MonetaryInput[]): Decimal {
  return amounts.reduce<Decimal>((sum, val) => sum.add(new Decimal(val)), new Decimal(0));
}

export function subtractAmounts(a: MonetaryInput, b: MonetaryInput): Decimal {
  return new Decimal(a).minus(b);
}

export function multiplyAmount(a: MonetaryInput, b: MonetaryInput): Decimal {
  return new Decimal(a).times(b);
}

export function divideAmount(a: MonetaryInput, b: MonetaryInput): Decimal {
  return new Decimal(a).div(b);
}

export function compareAmounts(a: MonetaryInput, b: MonetaryInput): number {
  return new Decimal(a).comparedTo(b);
}

export function isAmountZero(value: MonetaryInput, tolerance = 0.01): boolean {
  return new Decimal(value).abs().lessThanOrEqualTo(tolerance);
}

export function formatCurrency(
  value: MonetaryInput,
  currency: string = "SGD",
  decimals = 2
): string {
  const amount = formatAmount(value, decimals);
  return `${currency} ${amount}`;
}

function getLocaleSeparators(locale: string) {
  const group = new Intl.NumberFormat(locale, { useGrouping: true })
    .formatToParts(1000)
    .find((part) => part.type === "group")?.value ?? ",";
  const decimal = new Intl.NumberFormat(locale)
    .formatToParts(1.1)
    .find((part) => part.type === "decimal")?.value ?? ".";
  return { group, decimal };
}

function groupIntegerPart(value: string, groupSeparator: string, useGrouping: boolean): string {
  if (!useGrouping) return value;
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, groupSeparator);
}

export function formatCurrencyLocale(
  value: MonetaryInput,
  currency: string = "SGD",
  locale: string = "en-US",
  options?: Intl.NumberFormatOptions
): string {
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    ...options,
  });
  const resolved = formatter.resolvedOptions();
  const maximumFractionDigits = options?.maximumFractionDigits ?? resolved.maximumFractionDigits ?? 2;
  const minimumFractionDigits = options?.minimumFractionDigits ?? resolved.minimumFractionDigits ?? 0;
  const amount = new Decimal(value).toDecimalPlaces(maximumFractionDigits);
  const [integerPart, rawFractionPart = ""] = amount.abs().toFixed(maximumFractionDigits).split(".");
  const { group, decimal } = getLocaleSeparators(locale);
  const groupedInteger = groupIntegerPart(integerPart, group, options?.useGrouping !== false);
  let normalizedFractionPart = rawFractionPart;
  while (normalizedFractionPart.length > minimumFractionDigits && normalizedFractionPart.endsWith("0")) {
    normalizedFractionPart = normalizedFractionPart.slice(0, -1);
  }
  const amountText = normalizedFractionPart
    ? `${groupedInteger}${decimal}${normalizedFractionPart}`
    : groupedInteger;
  let integerInserted = false;

  return formatter
    .formatToParts(amount.isNegative() ? -1 : 1)
    .map((part) => {
      if (part.type === "integer") {
        if (integerInserted) return "";
        integerInserted = true;
        return amountText;
      }
      if (part.type === "group" || part.type === "decimal" || part.type === "fraction") {
        return "";
      }
      return part.value;
    })
    .join("");
}
