import Decimal from "decimal.js";

import { FloatNotAllowedError } from "./errors";
import type { QuantityInput } from "./quantity";

function coerce(value: QuantityInput, what = "quantity value"): Decimal {
  if (value instanceof Decimal) return value;
  if (typeof value === "string") return new Decimal(value);
  throw new FloatNotAllowedError(`${what} must be a Decimal or decimal string, not a number`);
}

function getLocaleSeparators(locale: string) {
  const group =
    new Intl.NumberFormat(locale, { useGrouping: true })
      .formatToParts(1000)
      .find((part) => part.type === "group")?.value ?? ",";
  return { group };
}

function groupIntegerPart(value: string, groupSeparator: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, groupSeparator);
}

export function formatQuantity(value: QuantityInput): string {
  const amount = coerce(value);
  if (!amount.isFinite()) throw new FloatNotAllowedError("quantity value must be finite");

  const { group } = getLocaleSeparators("en-US");
  const sign = amount.isNegative() ? "-" : "";
  const [integerPart, rawFractionPart = ""] = amount.abs().toFixed().split(".");
  const groupedInteger = groupIntegerPart(integerPart, group);
  const fractionPart = rawFractionPart.replace(/0+$/, "");

  if (!fractionPart) {
    return `${sign}${groupedInteger}`;
  }

  const paddedFraction = fractionPart.length === 1 ? `${fractionPart}0` : fractionPart;
  return `${sign}${groupedInteger}.${paddedFraction}`;
}
