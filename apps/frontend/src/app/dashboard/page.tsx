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

const toNumber = (value: number | string) => typeof value === "string" ? Number(value) : value;
const formatCurrency = (currency: string, value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
const formatMonthLabel = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short" });

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
  const incomeStart = useMemo(() => formatDateInput(new Date(today.getFullYear(), today.getMonth() - 11, 1)), [today]);
  const incomeEnd = useMemo(() => formatDateInput(today), [today]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [balanceData, incomeData, statsData, unmatchedData, journalData] = await Promise.all([
        apiFetch<BalanceSheetResponse>("/api/reports/balance-sheet"),
        apiFetch<IncomeStatementResponse>(`/api/reports/income-statement?start_date=${incomeStart}&end_date=${incomeEnd}`),
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
    const sortedAssets = [...balanceSheet.assets].sort((a, b) => toNumber(b.amount) - toNumber(a.amount));
    const target = sortedAssets[0];
    if (!target) return;
    try {
      const trendData = await apiFetch<TrendResponse>(`/api/reports/trend?account_id=${target.account_id}&period=monthly`);
      setTrend(trendData);
    } catch {
      setTrend(null);
    }
  }, [balanceSheet]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { fetchTrend(); }, [fetchTrend]);

  const netAssets = useMemo(() => balanceSheet ? toNumber(balanceSheet.total_assets) - toNumber(balanceSheet.total_liabilities) : 0, [balanceSheet]);
  const trendPoints = useMemo(() => trend ? trend.points.map((p) => ({ label: formatMonthLabel(p.period_start), value: toNumber(p.amount) })) : [], [trend]);
  const incomeBars = useMemo(() => incomeStatement ? incomeStatement.trends.slice(-6).map((t) => ({ label: formatMonthLabel(t.period_start), income: toNumber(t.total_income), expense: toNumber(t.total_expenses) })) : [], [incomeStatement]);
  const assetSegments = useMemo(() => {
    if (!balanceSheet) return [];
    const palette = ["#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"];
    return balanceSheet.assets.filter((a) => toNumber(a.amount) > 0).sort((a, b) => toNumber(b.amount) - toNumber(a.amount)).slice(0, 5).map((a, i) => ({ label: a.name, value: toNumber(a.amount), color: palette[i % palette.length] }));
  }, [balanceSheet]);

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[60vh]">
        <div className="text-center text-muted">
          <div className="inline-block w-6 h-6 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
          <p className="text-sm">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center max-w-lg mx-auto">
          <h1 className="text-xl font-semibold mb-2">Welcome to Finance Report</h1>
          <p className="text-muted mb-4 text-sm">{error}</p>
          <div className="grid gap-3 sm:grid-cols-3 mb-6">
            <Link href="/accounts" className="card p-4 hover:border-[var(--accent)] transition-colors text-center">
              <span className="text-2xl block mb-1">🏦</span>
              <span className="text-sm font-medium">Accounts</span>
            </Link>
            <Link href="/statements" className="card p-4 hover:border-[var(--accent)] transition-colors text-center">
              <span className="text-2xl block mb-1">📄</span>
              <span className="text-sm font-medium">Statements</span>
            </Link>
            <Link href="/journal" className="card p-4 hover:border-[var(--accent)] transition-colors text-center">
              <span className="text-2xl block mb-1">📝</span>
              <span className="text-sm font-medium">Journal</span>
            </Link>
          </div>
          <button onClick={fetchData} className="btn-secondary">Retry Connection</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="page-header flex items-center justify-between">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-description">Track net assets, cash momentum, and reconciliation risk</p>
        </div>
        <div className="flex gap-2">
          <Link href="/reports/balance-sheet" className="btn-secondary text-sm">Balance Sheet</Link>
          <Link href="/reports/income-statement" className="btn-secondary text-sm">Income Statement</Link>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Total Assets</p>
          <p className="text-2xl font-semibold text-[var(--success)] mt-1">
            {balanceSheet ? formatCurrency(balanceSheet.currency, toNumber(balanceSheet.total_assets)) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">As of {balanceSheet?.as_of_date}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Total Liabilities</p>
          <p className="text-2xl font-semibold text-[var(--error)] mt-1">
            {balanceSheet ? formatCurrency(balanceSheet.currency, toNumber(balanceSheet.total_liabilities)) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">Obligations</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Net Assets</p>
          <p className="text-2xl font-semibold mt-1">
            {balanceSheet ? formatCurrency(balanceSheet.currency, netAssets) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">{balanceSheet?.is_balanced ? "✓ Balanced" : "⚠ Drift"}</p>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Asset Trend</p>
          <h3 className="font-semibold mt-1 mb-4">{trend ? "Last 12 months" : "No trend data"}</h3>
          {trendPoints.length ? <TrendChart points={trendPoints} /> : <p className="text-sm text-muted">Add activity to unlock trends.</p>}
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Asset Mix</p>
          <h3 className="font-semibold mt-1 mb-4">Distribution</h3>
          {assetSegments.length ? <PieChart segments={assetSegments} centerLabel="Assets" /> : <p className="text-sm text-muted">No assets to chart yet.</p>}
        </div>
      </div>

      {/* Income/Expense + Reconciliation */}
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
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Reconciliation</p>
          <h3 className="font-semibold mt-1 mb-4">Risk radar</h3>
          <div className="space-y-2">
            <div className="flex justify-between p-3 rounded-md bg-[var(--success-muted)] text-sm">
              <span>Auto accepted</span><span className="font-semibold">{stats?.auto_accepted ?? 0}</span>
            </div>
            <div className="flex justify-between p-3 rounded-md bg-[var(--warning-muted)] text-sm">
              <span>Pending review</span><span className="font-semibold">{stats?.pending_review ?? 0}</span>
            </div>
            <div className="flex justify-between p-3 rounded-md bg-[var(--error-muted)] text-sm">
              <span>Unmatched</span><span className="font-semibold">{stats?.unmatched_transactions ?? 0}</span>
            </div>
            <Link href="/reconciliation" className="text-sm text-[var(--accent)] hover:underline inline-flex items-center gap-1">
              Review queue →
            </Link>
          </div>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide mb-3">Recent Entries</p>
          <div className="space-y-2">
            {recentEntries?.items?.length ? recentEntries.items.map((e) => (
              <div key={e.id} className="flex justify-between p-3 rounded-md bg-[var(--background-muted)] text-sm">
                <div><p className="font-medium">{e.memo || "Journal entry"}</p><p className="text-xs text-muted">{e.entry_date}</p></div>
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
                <div><p className="font-medium">{t.description}</p><p className="text-xs text-muted">{t.txn_date}</p></div>
                <span className="font-semibold">{balanceSheet ? formatCurrency(balanceSheet.currency, toNumber(t.amount)) : t.amount}</span>
              </div>
            )) : <p className="text-sm text-muted">No unmatched transactions.</p>}
            <Link href="/reconciliation/unmatched" className="text-sm text-[var(--warning)] hover:underline inline-flex items-center gap-1">
              Review unmatched →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
