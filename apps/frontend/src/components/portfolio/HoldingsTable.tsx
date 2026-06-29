"use client";

import Link from "next/link";
import { PortfolioHolding } from "@/lib/types";
import { compareAmounts, formatCurrencyLocale } from "@/lib/money";
import { formatQuantity } from "@/lib/quantity";
import { formatDateDisplay } from "@/lib/date";
import { formatSignedPercentFromPercentValue } from "@/lib/ratio/format";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";

interface HoldingsTableProps {
  holdings: PortfolioHolding[];
  showDisposed?: boolean;
}

function getPnlColor(value: string): string {
  const comparison = compareAmounts(value, "0");
  if (comparison === 0) return "";
  return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

export function HoldingsTable({
  holdings,
  showDisposed = false,
}: HoldingsTableProps) {
  const filtered = showDisposed
    ? holdings
    : holdings.filter((h) => h.status === "active");

  if (filtered.length === 0) {
    return (
      <div className="card p-8 text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--background-muted)] text-muted mb-4">
          <svg
            className="w-6 h-6"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
            />
          </svg>
        </div>
        <p className="text-muted">No holdings found</p>
        <p className="text-sm text-muted mt-1">
          Upload brokerage statements and reconcile to see holdings.
        </p>
      </div>
    );
  }

  // Group by broker/account
  const grouped = filtered.reduce(
    (groups, h) => {
      const key = h.account_name ?? "Unknown";
      if (!groups[key]) groups[key] = [];
      groups[key].push(h);
      return groups;
    },
    {} as Record<string, PortfolioHolding[]>,
  );

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([broker, brokerHoldings]) => (
        <div key={broker} className="card">
          <div className="card-header flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="badge badge-primary">{broker}</span>
              <span className="text-xs text-muted">
                {brokerHoldings.length} holdings
              </span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left px-4 py-2 font-medium">Asset</th>
                  <th className="text-right px-4 py-2 font-medium">Qty</th>
                  <th className="text-right px-4 py-2 font-medium">
                    Cost Basis
                  </th>
                  <th className="text-right px-4 py-2 font-medium">
                    Market Value
                  </th>
                  <th className="text-right px-4 py-2 font-medium">P&L</th>
                  <th className="text-right px-4 py-2 font-medium">P&L %</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {brokerHoldings.map((h) => (
                  <tr
                    key={h.id}
                    className="hover:bg-[var(--background-muted)]/50 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <Link
                          href={`/portfolio/${encodeURIComponent(h.asset_identifier)}`}
                          className="font-medium font-mono text-[var(--accent)] hover:underline"
                        >
                          {h.asset_identifier}
                        </Link>
                        <ProvenanceBadge provenance={h.provenance} />
                      </span>
                      <div className="text-xs text-muted mt-0.5">
                        {formatDateDisplay(h.acquisition_date)}
                        {h.sector && ` · ${h.sector}`}
                        {/* #1487: a foreign holding's values below are shown in
                            the reporting currency — surface its native currency
                            so the denomination is never hidden. */}
                        {h.native_currency && h.native_currency !== h.currency && (
                          <span title={`Denominated in ${h.native_currency}; values shown in ${h.currency}`}>
                            {` · ${h.native_currency}-denominated`}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {formatQuantity(h.quantity)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {formatCurrencyLocale(h.cost_basis, h.currency)}
                    </td>
                    <td className="px-4 py-2 text-right font-medium">
                      {formatCurrencyLocale(h.market_value, h.currency)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-medium ${getPnlColor(h.unrealized_pnl)}`}
                    >
                      {formatCurrencyLocale(h.unrealized_pnl, h.currency)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right ${getPnlColor(h.unrealized_pnl_percent)}`}
                    >
                      {formatSignedPercentFromPercentValue(
                        h.unrealized_pnl_percent,
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`badge ${h.status === "active" ? "badge-success" : "badge-muted"}`}
                      >
                        {h.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
