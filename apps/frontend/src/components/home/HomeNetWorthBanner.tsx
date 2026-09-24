"use client";

import ProcessingSummaryCard from "@/components/ProcessingSummaryCard";
import { InfoHint } from "@/components/ui/InfoHint";
import { OpeningBalanceWarningBanner } from "@/components/reports/OpeningBalanceWarningBanner";
import { formatDateDisplay } from "@/lib/date";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { percentNumberFromParts } from "@/lib/audit/ratio/format";
import { coverageLabel } from "@/lib/statusLabels";
import type { BalanceSheetResponse, ReconciliationStatsResponse } from "@/lib/types";
import type Decimal from "decimal.js";

interface HomeNetWorthBannerProps {
  balanceSheet: BalanceSheetResponse | null;
  netAssets: Decimal;
  includeRestricted: boolean;
  setIncludeRestricted: (include: boolean) => void;
  stats: ReconciliationStatsResponse | null;
}

export function HomeNetWorthBanner({
  balanceSheet,
  netAssets,
  includeRestricted,
  setIncludeRestricted,
  stats,
}: HomeNetWorthBannerProps) {
  return (
    <>
      {/* KPI Cards — Net Worth lives in the hero banner below, so it is not
          duplicated here as a "Net Assets" card. */}
      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <ProcessingSummaryCard />
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">
            Total Assets
          </p>
          <p className="text-2xl font-semibold text-[var(--success)] mt-1">
            {balanceSheet
              ? formatCurrencyLocale(
                  balanceSheet.total_assets,
                  balanceSheet.currency,
                  "en-US",
                  { maximumFractionDigits: 0 },
                )
              : "—"}
          </p>
          <p className="text-xs text-muted mt-1">
            As of{" "}
            {balanceSheet?.as_of_date
              ? formatDateDisplay(balanceSheet.as_of_date)
              : "—"}
          </p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">
            Total Liabilities
          </p>
          <p className="text-2xl font-semibold text-[var(--error)] mt-1">
            {balanceSheet
              ? formatCurrencyLocale(
                  balanceSheet.total_liabilities,
                  balanceSheet.currency,
                  "en-US",
                  { maximumFractionDigits: 0 },
                )
              : "—"}
          </p>
          <p className="text-xs text-muted mt-1">Obligations</p>
        </div>
      </div>

      {/* #1486: surface the opening-balance gate here too — net worth can
          render negative/incomplete until opening balances are recorded. */}
      <OpeningBalanceWarningBanner
        warnings={balanceSheet?.opening_balance_warnings}
      />

      {/* Hero: Net Worth Banner (C2 + C3) */}
      {balanceSheet && (
        <div className="card p-6 mb-6 bg-gradient-to-r from-[var(--accent-muted)] to-[var(--background-card)] border border-[var(--accent)]/30">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <p className="text-xs text-muted uppercase tracking-wide mb-1">
                Net Worth
              </p>
              <p
                className={`text-4xl font-bold ${netAssets.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}
              >
                {formatCurrencyLocale(
                  netAssets,
                  balanceSheet.currency,
                  "en-US",
                  { maximumFractionDigits: 0 },
                )}
              </p>
              <p className="text-xs text-muted mt-1 inline-flex items-center">
                As of{" "}
                {balanceSheet?.as_of_date
                  ? formatDateDisplay(balanceSheet.as_of_date)
                  : ""}{" "}
                ·{" "}
                {balanceSheet.is_balanced
                  ? "✓ Books balanced"
                  : "⚠ Equation drift"}
                <InfoHint
                  term={balanceSheet.is_balanced ? "balanced" : "drift"}
                  label={
                    balanceSheet.is_balanced
                      ? "Books balanced"
                      : "Equation drift"
                  }
                />
              </p>
              <label className="mt-3 inline-flex items-center gap-2 text-sm text-muted">
                <input
                  type="checkbox"
                  checked={includeRestricted}
                  onChange={(event) =>
                    setIncludeRestricted(event.target.checked)
                  }
                  className="rounded"
                />
                Include restricted holdings
              </label>
            </div>
            {stats &&
              (() => {
                const total = stats.total_transactions ?? 0;
                const clean = stats.matched_transactions ?? 0;
                const pct =
                  total > 0
                    ? (percentNumberFromParts(
                        String(clean),
                        String(total),
                        { dp: 0, fallback: 0 },
                      ) ?? 0)
                    : 100;
                const barColor =
                  pct >= 85
                    ? "var(--success)"
                    : pct >= 60
                      ? "var(--warning)"
                      : "var(--error)";
                return (
                  <div className="min-w-[180px]">
                    <div className="flex justify-between text-xs text-muted mb-1">
                      <span className="inline-flex items-center">
                        Reconciliation coverage
                        <InfoHint
                          term="reconciliation_coverage"
                          label="Reconciliation coverage"
                        />
                      </span>
                      <span
                        className="font-medium"
                        style={{ color: barColor }}
                      >
                        {pct}%
                        <span className="ml-1 font-normal">
                          {coverageLabel(pct)}
                        </span>
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: barColor,
                        }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-muted mt-1">
                      <span>{clean} matched</span>
                      <span>
                        {stats.unmatched_transactions ?? 0} unmatched
                      </span>
                    </div>
                  </div>
                );
              })()}
          </div>
        </div>
      )}
    </>
  );
}
