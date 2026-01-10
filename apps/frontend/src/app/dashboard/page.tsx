"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";
import { formatDateInput } from "@/lib/date";
import { BarChart } from "@/components/charts/BarChart";
import { PieChart } from "@/components/charts/PieChart";
import { TrendChart } from "@/components/charts/TrendChart";

interface ReportLine {
  account_id: string;
  name: string;
  type: string;
  parent_id?: string | null;
  amount: number | string;
}

interface BalanceSheetResponse {
  as_of_date: string;
  currency: string;
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets: number | string;
  total_liabilities: number | string;
  total_equity: number | string;
  equation_delta: number | string;
  is_balanced: boolean;
}

interface IncomeStatementTrend {
  period_start: string;
  period_end: string;
  total_income: number | string;
  total_expenses: number | string;
  net_income: number | string;
}

interface IncomeStatementResponse {
  start_date: string;
  end_date: string;
  currency: string;
  income: ReportLine[];
  expenses: ReportLine[];
  total_income: number | string;
  total_expenses: number | string;
  net_income: number | string;
  trends: IncomeStatementTrend[];
}

interface TrendPoint {
  period_start: string;
  period_end: string;
  amount: number | string;
}

interface TrendResponse {
  account_id: string;
  currency: string;
  period: string;
  points: TrendPoint[];
}

interface ReconciliationStatsResponse {
  total_transactions: number;
  matched_transactions: number;
  unmatched_transactions: number;
  pending_review: number;
  auto_accepted: number;
  match_rate: number;
}

interface BankTransactionSummary {
  id: string;
  txn_date: string;
  description: string;
  amount: number | string;
  direction: "IN" | "OUT";
  reference?: string | null;
}

interface UnmatchedTransactionsResponse {
  items: BankTransactionSummary[];
  total: number;
}

interface JournalEntrySummary {
  id: string;
  entry_date: string;
  memo?: string | null;
  status: string;
}

interface JournalEntryListResponse {
  items: JournalEntrySummary[];
  total: number;
}

const toNumber = (value: number | string) =>
  typeof value === "string" ? Number(value) : value;

const formatCurrency = (currency: string, value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);

const formatMonthLabel = (value: string) =>
  new Date(value).toLocaleDateString("en-US", { month: "short" });

export default function DashboardPage() {
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheetResponse | null>(null);
  const [incomeStatement, setIncomeStatement] = useState<IncomeStatementResponse | null>(null);
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedTransactionsResponse | null>(null);
  const [recentEntries, setRecentEntries] = useState<JournalEntryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const today = useMemo(() => new Date(), []);
  const incomeStart = useMemo(() => {
    const start = new Date(today.getFullYear(), today.getMonth() - 11, 1);
    return formatDateInput(start);
  }, [today]);
  const incomeEnd = useMemo(() => formatDateInput(today), [today]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [balanceData, incomeData, statsData, unmatchedData, journalData] =
        await Promise.all([
          apiFetch<BalanceSheetResponse>("/api/reports/balance-sheet"),
          apiFetch<IncomeStatementResponse>(
            `/api/reports/income-statement?start_date=${incomeStart}&end_date=${incomeEnd}`
          ),
          apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
          apiFetch<UnmatchedTransactionsResponse>("/api/reconciliation/unmatched?limit=5"),
          apiFetch<JournalEntryListResponse>("/api/journal-entries?page=1&page_size=5"),
        ]);

      setBalanceSheet(balanceData);
      setIncomeStatement(incomeData);
      setStats(statsData);
      setUnmatched(unmatchedData);
      setRecentEntries(journalData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard data.");
    } finally {
      setLoading(false);
    }
  }, [incomeEnd, incomeStart]);

  const fetchTrend = useCallback(async () => {
    if (!balanceSheet) return;
    const sortedAssets = [...balanceSheet.assets].sort(
      (a, b) => toNumber(b.amount) - toNumber(a.amount)
    );
    const target = sortedAssets[0];
    if (!target) return;
    try {
      const trendData = await apiFetch<TrendResponse>(
        `/api/reports/trend?account_id=${target.account_id}&period=monthly`
      );
      setTrend(trendData);
    } catch {
      setTrend(null);
    }
  }, [balanceSheet]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    fetchTrend();
  }, [fetchTrend]);

  const netAssets = useMemo(() => {
    if (!balanceSheet) return 0;
    return toNumber(balanceSheet.total_assets) - toNumber(balanceSheet.total_liabilities);
  }, [balanceSheet]);

  const trendPoints = useMemo(() => {
    if (!trend) return [];
    return trend.points.map((point) => ({
      label: formatMonthLabel(point.period_start),
      value: toNumber(point.amount),
    }));
  }, [trend]);

  const incomeBars = useMemo(() => {
    if (!incomeStatement) return [];
    return incomeStatement.trends.slice(-6).map((trendItem) => ({
      label: formatMonthLabel(trendItem.period_start),
      income: toNumber(trendItem.total_income),
      expense: toNumber(trendItem.total_expenses),
    }));
  }, [incomeStatement]);

  const assetSegments = useMemo(() => {
    if (!balanceSheet) return [];
    const palette = ["#0f766e", "#14b8a6", "#f59e0b", "#f97316", "#e11d48"];
    return balanceSheet.assets
      .filter((asset) => toNumber(asset.amount) > 0)
      .sort((a, b) => toNumber(b.amount) - toNumber(a.amount))
      .slice(0, 5)
      .map((asset, index) => ({
        label: asset.name,
        value: toNumber(asset.amount),
        color: palette[index % palette.length],
      }));
  }, [balanceSheet]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f8f4ed] flex items-center justify-center text-slate-600">
        Loading dashboard…
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#f8f4ed] flex flex-col items-center justify-center text-slate-600 gap-4">
        <p>{error}</p>
        <button
          onClick={fetchData}
          className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f5f0e6_0%,#f7efe1_45%,#ecf1f0_100%)] text-[#13201b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-24 right-[-4rem] h-64 w-64 rounded-full bg-[#ffe1b2] blur-3xl opacity-80"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-4rem] h-72 w-72 rounded-full bg-[#baf3e6] blur-3xl opacity-60"></div>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(#0f1f17_0.6px,transparent_0.6px)] opacity-10 [background-size:14px_14px]"></div>

        <div className="relative z-10 mx-auto max-w-7xl px-6 py-10">
          <header className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-3 animate-rise">
              <p className="text-xs uppercase tracking-[0.4em] text-emerald-700">
                Financial Control Tower
              </p>
              <h1 className="text-4xl sm:text-5xl font-semibold text-[#0f1f17]">
                Dashboard
              </h1>
              <p className="max-w-xl text-base text-[#334136]">
                Track net assets, cash momentum, and reconciliation risk in one snapshot.
              </p>
            </div>
            <nav className="flex flex-wrap gap-3 text-sm">
              <Link
                href="/reports/balance-sheet"
                className="rounded-full border border-emerald-200 bg-white/80 px-4 py-2 text-emerald-800 shadow-sm"
              >
                Balance Sheet
              </Link>
              <Link
                href="/reports/income-statement"
                className="rounded-full border border-amber-200 bg-white/80 px-4 py-2 text-amber-800 shadow-sm"
              >
                Income Statement
              </Link>
            </nav>
          </header>

          <section className="mt-10 grid gap-4 md:grid-cols-3">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Total Assets</p>
              <p className="mt-3 text-3xl font-semibold text-emerald-700">
                {balanceSheet
                  ? formatCurrency(balanceSheet.currency, toNumber(balanceSheet.total_assets))
                  : "—"}
              </p>
              <p className="mt-2 text-xs text-slate-500">As of {balanceSheet?.as_of_date}</p>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Total Liabilities</p>
              <p className="mt-3 text-3xl font-semibold text-rose-500">
                {balanceSheet
                  ? formatCurrency(balanceSheet.currency, toNumber(balanceSheet.total_liabilities))
                  : "—"}
              </p>
              <p className="mt-2 text-xs text-slate-500">Obligations in view</p>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Net Assets</p>
              <p className="mt-3 text-3xl font-semibold text-slate-800">
                {balanceSheet ? formatCurrency(balanceSheet.currency, netAssets) : "—"}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                {balanceSheet?.is_balanced ? "Equation verified" : "Equation drift"}
              </p>
            </div>
          </section>

          <section className="mt-10 grid gap-6 lg:grid-cols-[1.3fr,0.9fr]">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                    Asset Trend
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">
                    {trend ? "Last 12 months" : "No trend data"}
                  </h2>
                </div>
                <span className="text-xs text-slate-500">Primary asset account</span>
              </div>
              <div className="mt-6">
                {trendPoints.length ? (
                  <TrendChart points={trendPoints} />
                ) : (
                  <p className="text-sm text-slate-500">Add activity to unlock trends.</p>
                )}
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Asset Mix</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">
                Distribution snapshot
              </h2>
              <div className="mt-4">
                {assetSegments.length ? (
                  <PieChart segments={assetSegments} centerLabel="Assets" />
                ) : (
                  <p className="text-sm text-slate-500">No assets to chart yet.</p>
                )}
              </div>
            </div>
          </section>

          <section className="mt-10 grid gap-6 lg:grid-cols-[1.2fr,1fr]">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Income vs Expense
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">
                Monthly comparison
              </h2>
              <div className="mt-6">
                {incomeBars.length ? (
                  <BarChart
                    items={incomeBars}
                    ariaLabel="Monthly income and expense comparison"
                  />
                ) : (
                  <p className="text-sm text-slate-500">No income data available.</p>
                )}
              </div>
              <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
                  Income
                </span>
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-400"></span>
                  Expense
                </span>
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Reconciliation</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">Risk radar</h2>
              <div className="mt-4 space-y-4">
                <div className="flex items-center justify-between rounded-2xl bg-emerald-50/70 px-4 py-3 text-sm text-emerald-800">
                  <span>Auto accepted</span>
                  <span className="font-semibold">{stats?.auto_accepted ?? 0}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl bg-amber-50/70 px-4 py-3 text-sm text-amber-800">
                  <span>Pending review</span>
                  <span className="font-semibold">{stats?.pending_review ?? 0}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl bg-rose-50/70 px-4 py-3 text-sm text-rose-700">
                  <span>Unmatched</span>
                  <span className="font-semibold">{stats?.unmatched_transactions ?? 0}</span>
                </div>
                <Link
                  href="/reconciliation"
                  className="inline-flex items-center gap-2 text-sm text-emerald-700"
                >
                  Review reconciliation queue →
                </Link>
              </div>
            </div>
          </section>

          <section className="mt-10 grid gap-6 lg:grid-cols-2">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Recent entries</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">Latest activity</h2>
              <div className="mt-4 space-y-3">
                {recentEntries?.items?.length ? (
                  recentEntries.items.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-start justify-between rounded-2xl border border-slate-100 bg-white/80 px-4 py-3 text-sm"
                    >
                      <div>
                        <p className="font-medium text-slate-800">
                          {entry.memo || "Journal entry"}
                        </p>
                        <p className="text-xs text-slate-500">{entry.entry_date}</p>
                      </div>
                      <span className="text-xs uppercase tracking-[0.2em] text-slate-400">
                        {entry.status}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">No recent journal entries.</p>
                )}
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Unmatched alerts</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">Needs attention</h2>
              <div className="mt-4 space-y-3">
                {unmatched?.items?.length ? (
                  unmatched.items.map((txn) => (
                    <div
                      key={txn.id}
                      className="flex items-start justify-between rounded-2xl border border-amber-100 bg-amber-50/60 px-4 py-3 text-sm text-amber-900"
                    >
                      <div>
                        <p className="font-medium">{txn.description}</p>
                        <p className="text-xs text-amber-700">{txn.txn_date}</p>
                      </div>
                      <span className="text-sm font-semibold">
                        {balanceSheet
                          ? formatCurrency(
                              balanceSheet.currency,
                              toNumber(txn.amount)
                            )
                          : txn.amount}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">No unmatched transactions.</p>
                )}
                <Link
                  href="/reconciliation/unmatched"
                  className="inline-flex items-center gap-2 text-sm text-amber-700"
                >
                  Review unmatched transactions →
                </Link>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
