"use client";

import Link from "next/link";
import { useState } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { PieChart } from "@/components/charts/PieChart";
import { TrendChart } from "@/components/charts/TrendChart";
import { formatDateDisplay } from "@/lib/date";
import { compareAmounts, formatCurrencyLocale } from "@/lib/audit/money";
import type {
  BalanceSheetResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  TrendResponse,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

interface HomeAnalyticsSectionProps {
  balanceSheet: BalanceSheetResponse | null;
  stats: ReconciliationStatsResponse | null;
  recentEntries: JournalEntryListResponse | null;
  unmatched: UnmatchedTransactionsResponse | null;
  trend: TrendResponse | null;
  trendAccountName: string;
  trendAccountId: string | null;
  setTrendAccountId: (id: string | null) => void;
  trendPoints: Array<{ label: string; value: number }>;
  assetSegments: Array<{ label: string; value: number; color: string }>;
  incomeBars: Array<{ label: string; income: number; expense: number }>;
}

export function HomeAnalyticsSection({
  balanceSheet,
  stats,
  recentEntries,
  unmatched,
  trend,
  trendAccountName,
  trendAccountId,
  setTrendAccountId,
  trendPoints,
  assetSegments,
  incomeBars,
}: HomeAnalyticsSectionProps) {
  // EPIC-022 PR4: Home defaults to a lean view; heavy charts are opt-in.
  const [showAnalytics, setShowAnalytics] = useState(false);

  return (
    <>
      <div className="mb-6">
        <button
          type="button"
          onClick={() => setShowAnalytics((open) => !open)}
          className="btn-secondary inline-flex items-center gap-2 text-sm"
          aria-expanded={showAnalytics}
        >
          {showAnalytics ? "Hide analytics" : "Show analytics"}
        </button>
      </div>

      {showAnalytics && (
        <>
          {/* Charts Row */}
          <div className="mb-6">
            <NetWorthTimeSeriesChart />
          </div>

          <div className="grid gap-4 lg:grid-cols-2 mb-6">
            <div className="card p-5">
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs text-muted uppercase tracking-wide">
                  Asset Trend
                </p>
                {balanceSheet &&
                  balanceSheet.assets &&
                  balanceSheet.assets.length > 1 && (
                    <select
                      value={trendAccountId ?? ""}
                      onChange={(e) => setTrendAccountId(e.target.value || null)}
                      className="input text-xs py-1 px-2 w-auto"
                    >
                      <option value="">Top Asset</option>
                      {[...balanceSheet.assets]
                        .sort((a, b) => compareAmounts(b.amount, a.amount))
                        .map((a) => (
                          <option key={a.account_id} value={a.account_id}>
                            {a.name}
                          </option>
                        ))}
                    </select>
                  )}
              </div>
              <h3 className="font-semibold mt-1 mb-4">
                {trendAccountName} —{" "}
                {trend ? "Last 12 months" : "No trend data"}
              </h3>
              {trendPoints.length ? (
                <TrendChart points={trendPoints} />
              ) : (
                <p className="text-sm text-muted">
                  Add activity to unlock trends.
                </p>
              )}
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">
                Asset Mix
              </p>
              <h3 className="font-semibold mt-1 mb-4">Distribution</h3>
              {assetSegments.length ? (
                <PieChart segments={assetSegments} centerLabel="Assets" />
              ) : (
                <p className="text-sm text-muted">
                  No assets to chart yet.
                </p>
              )}
            </div>
          </div>

          {/* Income/Expense + Reconciliation */}
          <div className="grid gap-4 lg:grid-cols-2 mb-6">
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">
                Income vs Expense
              </p>
              <h3 className="font-semibold mt-1 mb-4">Monthly comparison</h3>
              {incomeBars.length ? (
                <>
                  <BarChart
                    items={incomeBars}
                    ariaLabel="Monthly income and expense comparison"
                  />
                  <div className="mt-3 flex gap-4 text-xs text-muted">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-[var(--success)]" />
                      Income
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-[var(--error)]" />
                      Expense
                    </span>
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted">
                  No income data available.
                </p>
              )}
            </div>
            {/* EPIC-022 AC22.16.2 (#1116): the risk radar is an expansion of the
                single confidence-ranked attention queue, not a parallel set of links
                into Advanced reconciliation internals. The whole card routes to
                /attention; the counts stay as read-only context. */}
            <Link
              href="/attention"
              className="card p-5 block hover:border-[var(--accent)] transition-colors"
            >
              <p className="text-xs text-muted uppercase tracking-wide">
                Reconciliation
              </p>
              <h3 className="font-semibold mt-1 mb-4">Risk radar</h3>
              <div className="space-y-2">
                <div className="flex justify-between p-3 rounded-md bg-[var(--success-muted)] text-sm">
                  <span>Auto accepted</span>
                  <span className="font-semibold">
                    {stats?.auto_accepted ?? 0}
                  </span>
                </div>
                <div className="flex justify-between p-3 rounded-md bg-[var(--warning-muted)] text-sm">
                  <span>Pending review</span>
                  <span className="font-semibold">
                    {stats?.pending_review ?? 0}
                  </span>
                </div>
                <div className="flex justify-between p-3 rounded-md bg-[var(--error-muted)] text-sm">
                  <span>Unmatched</span>
                  <span className="font-semibold">
                    {stats?.unmatched_transactions ?? 0}
                  </span>
                </div>
              </div>
              <span className="mt-3 inline-flex items-center gap-1 text-sm text-[var(--accent)]">
                Review in attention queue →
              </span>
            </Link>
          </div>

          {/* Recent Activity */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide mb-3">
                Recent Entries
              </p>
              <div className="space-y-2">
                {recentEntries?.items?.length ? (
                  recentEntries.items.map((e) => (
                    <div
                      key={e.id}
                      className="flex justify-between p-3 rounded-md bg-[var(--background-muted)] text-sm"
                    >
                      <div>
                        <p className="font-medium">
                          {e.memo || "Journal entry"}
                        </p>
                        <p className="text-xs text-muted">
                          {formatDateDisplay(e.entry_date)}
                        </p>
                      </div>
                      <span className="badge badge-muted">
                        {e.status}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted">
                    No recent journal entries.
                  </p>
                )}
              </div>
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide mb-3">
                Unmatched Alerts
              </p>
              <div className="space-y-2">
                {unmatched?.items?.length ? (
                  unmatched.items.map((t) => (
                    <div
                      key={t.id}
                      className="flex justify-between p-3 rounded-md bg-[var(--warning-muted)] text-sm"
                    >
                      <div>
                        <p className="font-medium">{t.description}</p>
                        <p className="text-xs text-muted">
                          {formatDateDisplay(t.txn_date)}
                        </p>
                      </div>
                      <span className="font-semibold">
                        {balanceSheet
                          ? formatCurrencyLocale(
                              t.amount,
                              balanceSheet.currency,
                              "en-US",
                              { maximumFractionDigits: 0 },
                            )
                          : t.amount}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted">
                    No unmatched transactions.
                  </p>
                )}
                {/* EPIC-022 AC22.16.2 (#1116): route to the unified attention queue
                    rather than the Advanced reconciliation/unmatched surface. */}
                <Link
                  href="/attention"
                  className="text-sm text-[var(--warning)] hover:underline inline-flex items-center gap-1"
                >
                  Review unmatched →
                </Link>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
