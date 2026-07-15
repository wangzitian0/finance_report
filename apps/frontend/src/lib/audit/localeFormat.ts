/**
 * Locale-aware number-formatting primitives shared by money and quantity
 * display formatting (was duplicated near-identically between
 * lib/audit/money/format.ts and lib/audit/quantity/format.ts, #1868 S5).
 */

/** Group and decimal separator characters for a locale. */
export function getLocaleSeparators(locale: string): { group: string; decimal: string } {
  const group =
    new Intl.NumberFormat(locale, { useGrouping: true })
      .formatToParts(1000)
      .find((part) => part.type === "group")?.value ?? ",";
  const decimal =
    new Intl.NumberFormat(locale)
      .formatToParts(1.1)
      .find((part) => part.type === "decimal")?.value ?? ".";
  return { group, decimal };
}

/** Insert thousands separators into an integer-part digit string. */
export function groupIntegerPart(value: string, groupSeparator: string, useGrouping = true): string {
  if (!useGrouping) return value;
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, groupSeparator);
}
