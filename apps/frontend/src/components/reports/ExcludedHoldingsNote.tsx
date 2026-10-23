import { toDecimal, type MonetaryInput } from "@/lib/audit/money";
import { allocationClassLabel } from "@/lib/statusLabels";
import type { BalanceSheetResponse } from "@/lib/types";

type ExcludedHoldingRow = NonNullable<BalanceSheetResponse["excluded_holdings"]>[number];
type FormatMoney = (value: MonetaryInput, currency: string) => string;

/** One conversion gap: a missing rate, or a rate that did not convert. */
function gapText(warning: Record<string, string>): string {
  const pair = `${warning.currency} to ${warning.target_currency}`;
  return warning.type === "missing_fx_rate_excluded_holding" ? `no FX rate for ${pair}` : `FX conversion failed for ${pair}`;
}

/** A row without amounts has a valuation that did not convert: the text names each gap. */
function rowText(row: ExcludedHoldingRow, currency: string, formatMoney: FormatMoney): string {
  const label = allocationClassLabel(row.asset_class);
  if (row.net_worth === null || row.total_liabilities === null) {
    const gaps = [...new Set((row.warnings ?? []).map(gapText))].sort();
    return `${label}: amount not available (${gaps.join(", ")})`;
  }
  const liabilities = toDecimal(row.total_liabilities).isZero()
    ? ""
    : ` (net of ${formatMoney(row.total_liabilities, currency)} liabilities)`;
  return `${label} ${formatMoney(row.net_worth, currency)}${liabilities}`;
}

/**
 * Names each asset class that the restricted-holdings scope leaves out of a net worth (#2645).
 *
 * The balance sheet returns one row per excluded class. A class with excluded liabilities, for
 * example a property and its mortgage, shows its net and the liabilities. The note renders nothing
 * for the full scope.
 */
export function ExcludedHoldingsNote({
  rows,
  currency,
  formatMoney,
}: {
  rows: ExcludedHoldingRow[] | undefined;
  currency: string;
  formatMoney: FormatMoney;
}) {
  if (!rows?.length) return null;
  return (
    <div data-testid="excluded-holdings-note" className="mt-2 text-xs text-muted">
      <p>Excludes restricted and illiquid holdings:</p>
      <ul className="mt-0.5 space-y-0.5">
        {rows.map((row) => (
          <li key={row.asset_class}>{rowText(row, currency, formatMoney)}</li>
        ))}
      </ul>
    </div>
  );
}
