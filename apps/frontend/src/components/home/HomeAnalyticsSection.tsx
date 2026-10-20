"use client";

import Link from "next/link";
import { useState } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { PieChart } from "@/components/charts/PieChart";
import { TrendChart } from "@/components/charts/TrendChart";
import { formatDateDisplay } from "@/lib/date";
import { compareAmounts, formatCurrencyLocale } from "@/lib/audit/money";
import { formatPercentFromPercentValue, percentNumberFromParts } from "@/lib/audit/ratio/format";
import type {
  AnnualizedIncomeResponse,
  BalanceSheetResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  RestrictedHolding,
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
  annualizedIncome?: AnnualizedIncomeResponse | null;
  restrictedHoldings?: RestrictedHolding[];
}

const NO_FRAC = { maximumFractionDigits: 0 } as const;

export function HomeAnalyticsSection({
  balanceSheet, stats, recentEntries, unmatched, trend, trendAccountName,
  trendAccountId, setTrendAccountId, trendPoints, assetSegments, incomeBars,
  annualizedIncome = null, restrictedHoldings = [],
}: HomeAnalyticsSectionProps) {
  const [showAnalytics, setShowAnalytics] = useState(false);
  const fmtAnn = (v?: string | number) =>
    annualizedIncome && v != null ? formatCurrencyLocale(v, annualizedIncome.currency, "en-US", NO_FRAC) : "—";
  const totalTx = stats?.total_transactions ?? 0;
  const cleanTx = stats?.matched_transactions ?? 0;
  const reconPct = totalTx > 0 ? (percentNumberFromParts(String(cleanTx), String(totalTx), { dp: 0, fallback: 0 }) ?? 0) : 100;

  return (
    <>
      <div className="mb-6">
        <button type="button" onClick={() => setShowAnalytics((open) => !open)} className="btn-secondary inline-flex items-center gap-2 text-sm" aria-expanded={showAnalytics}>
          {showAnalytics ? "Hide analytics" : "Show analytics"}
        </button>
      </div>

      {showAnalytics && (
        <>
          <div className="grid gap-3 lg:grid-cols-3 mb-4">
            <div className="card p-3">
              <p className="text-xs text-muted uppercase tracking-wide">Annualized Income</p>
              <p className="text-lg font-semibold mt-0.5">{fmtAnn(annualizedIncome?.annualized_total)}</p>
              <p className="text-xs text-muted mt-0.5">As of {annualizedIncome?.as_of ? formatDateDisplay(annualizedIncome.as_of) : "—"}</p>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                {([["Salary", annualizedIncome?.annualized_salary], ["Bonus", annualizedIncome?.annualized_bonus], ["Dividend", annualizedIncome?.annualized_dividend]] as const).map(([label, val]) => (
                  <div key={label}><p className="text-muted">{label}</p><p className="font-medium">{fmtAnn(val)}</p></div>
                ))}
              </div>
            </div>

            <div className="card p-3">
              <p className="text-xs text-muted uppercase tracking-wide">Restricted Holdings</p>
              {restrictedHoldings.length ? (
                <div className="mt-2 space-y-1.5">
                  {restrictedHoldings.map((h) => (
                    <div key={`${h.ticker}-${h.unlock_date ?? "locked"}`} className="flex items-center justify-between gap-2 rounded-md bg-[var(--background-muted)] p-2 text-xs">
                      <div><p className="font-medium">{h.ticker}</p><p className="text-muted">Unlock {h.unlock_date ? formatDateDisplay(h.unlock_date) : "TBD"}</p></div>
                      <p className="font-semibold">{formatCurrencyLocale(h.fair_value, h.currency, "en-US", NO_FRAC)}</p>
                    </div>
                  ))}
                </div>
              ) : <p className="mt-2 text-xs text-muted">No restricted holdings.</p>}
            </div>

            <div className="card p-3">
              <p className="text-xs text-muted uppercase tracking-wide">Reconciliation coverage</p>
              {stats ? (
                <div className="mt-2 space-y-1.5 text-xs">
                  <div className="flex justify-between font-medium">
                    <span>{formatPercentFromPercentValue(String(reconPct), { dp: 0, fallback: "0%" })}</span>
                    <span className="text-muted">{cleanTx} matched</span>
                  </div>
                  <div className="h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                    <div className="h-full rounded-full bg-[var(--success)]" style={{ width: `${reconPct}%` }} />
                  </div>
                </div>
              ) : <p className="mt-2 text-xs text-muted">No reconciliation stats.</p>}
            </div>
          </div>

          <div className="mb-6"><NetWorthTimeSeriesChart /></div>

          <div className="grid gap-4 lg:grid-cols-2 mb-6">
            <div className="card p-5">
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs text-muted uppercase tracking-wide">Asset Trend</p>
                {balanceSheet?.assets && balanceSheet.assets.length > 1 && (
                  <select value={trendAccountId ?? ""} onChange={(e) => setTrendAccountId(e.target.value || null)} className="input text-xs py-1 px-2 w-auto">
                    <option value="">Top Asset</option>
                    {[...balanceSheet.assets].sort((a, b) => compareAmounts(b.amount, a.amount)).map((a) => (
                      <option key={a.account_id} value={a.account_id}>{a.name}</option>
                    ))}
                  </select>
                )}
              </div>
              <h3 className="font-semibold mt-1 mb-4">{trendAccountName} — {trend ? "Last 12 months" : "No trend data"}</h3>
              {trendPoints.length ? <TrendChart points={trendPoints} /> : <p className="text-sm text-muted">Add activity to unlock trends.</p>}
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Asset Mix</p>
              <h3 className="font-semibold mt-1 mb-4">Distribution</h3>
              {assetSegments.length ? <PieChart segments={assetSegments} centerLabel="Assets" /> : <p className="text-sm text-muted">No assets to chart yet.</p>}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2 mb-6">
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Income vs Expense</p>
              <h3 className="font-semibold mt-1 mb-4">Monthly comparison</h3>
              {incomeBars.length ? (
                <>
                  <BarChart items={incomeBars} ariaLabel="Monthly income and expense comparison" />
                  <div className="mt-3 flex gap-4 text-xs text-muted">
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[var(--success)]" />Income</span>
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[var(--error)]" />Expense</span>
                  </div>
                </>
              ) : <p className="text-sm text-muted">No income data available.</p>}
            </div>
            <Link href="/attention" className="card p-5 block hover:border-[var(--accent)] transition-colors">
              <p className="text-xs text-muted uppercase tracking-wide">Reconciliation</p>
              <h3 className="font-semibold mt-1 mb-4">Risk radar</h3>
              <div className="space-y-2">
                {([["Auto accepted", stats?.auto_accepted ?? 0, "bg-[var(--success-muted)]"], ["Pending review", stats?.pending_review ?? 0, "bg-[var(--warning-muted)]"], ["Unmatched", stats?.unmatched_transactions ?? 0, "bg-[var(--error-muted)]"]] as const).map(([label, val, bg]) => (
                  <div key={label} className={`flex justify-between p-3 rounded-md ${bg} text-sm`}><span>{label}</span><span className="font-semibold">{val}</span></div>
                ))}
              </div>
              <span className="mt-3 inline-flex items-center gap-1 text-sm text-[var(--accent)]">Review in attention queue →</span>
            </Link>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide mb-3">Recent Entries</p>
              <div className="space-y-2">
                {recentEntries?.items?.length ? recentEntries.items.map((e) => (
                  <div key={e.id} className="flex justify-between p-3 rounded-md bg-[var(--background-muted)] text-sm">
                    <div><p className="font-medium">{e.memo || "Journal entry"}</p><p className="text-xs text-muted">{formatDateDisplay(e.entry_date)}</p></div>
                    <span className="badge badge-muted">{e.status}</span>
                  </div>
                )) : <p className="text-sm text-muted">No recent journal entries.</p>}
              </div>
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide mb-3">Unmatched Alerts</p>
              <div className="space-y-2">
                {unmatched?.items?.length ? unmatched.items.map((t) => (
                  <div key={t.id} className="flex justify-between p-3 rounded-md bg-[var(--warning-muted)] text-sm">
                    <div><p className="font-medium">{t.description}</p><p className="text-xs text-muted">{formatDateDisplay(t.txn_date)}</p></div>
                    <span className="font-semibold">{balanceSheet ? formatCurrencyLocale(t.amount, balanceSheet.currency, "en-US", NO_FRAC) : t.amount}</span>
                  </div>
                )) : <p className="text-sm text-muted">No unmatched transactions.</p>}
                <Link href="/attention" className="text-sm text-[var(--warning)] hover:underline inline-flex items-center gap-1">Review unmatched →</Link>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
