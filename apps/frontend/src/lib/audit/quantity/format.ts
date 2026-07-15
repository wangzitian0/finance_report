import { coerce, type QuantityInput } from "./quantity";
import { getLocaleSeparators, groupIntegerPart } from "@/lib/audit/localeFormat";

export function formatQuantity(value: QuantityInput): string {
  // coerce() already rejects non-finite values (FloatNotAllowedError,
  // "quantity value must be finite") — no separate isFinite() check needed.
  const amount = coerce(value);

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
