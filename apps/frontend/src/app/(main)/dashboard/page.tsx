"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Landmark, FileText, BookOpen } from "lucide-react";
import ProcessingSummaryCard from "@/components/ProcessingSummaryCard";
import { UploadToReportHomePanel } from "@/components/workflow/WorkflowNotifications";

import { apiFetch } from "@/lib/api";
import { formatDateInput, formatDateDisplay, formatMonthLabel } from "@/lib/date";
import { amountToChartNumber, compareAmounts, formatCurrencyLocale, subtractAmounts, toDecimal } from "@/lib/currency";
import { BarChart } from "@/components/charts/BarChart";
import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { PieChart } from "@/components/charts/PieChart";
import { TrendChart } from "@/components/charts/TrendChart";
import {
  AccountListResponse,
  BankStatementListResponse,
  BalanceSheetResponse,
  AnnualizedIncomeResponse,
  IncomeStatementResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  RestrictedHolding,
  TrendResponse,
  UnmatchedTransactionsResponse
} from "@/lib/types";

const CHART_PALETTE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

const EMPTY_BALANCE_SHEET: BalanceSheetResponse = {
  as_of_date: "",
  currency: "SGD",
  assets: [],
  liabilities: [],
  equity: [],
  total_assets: "0",
  total_liabilities: "0",
  total_equity: "0",
  equation_delta: "0",
  is_balanced: true,
};

const EMPTY_INCOME_STATEMENT: IncomeStatementResponse = {
  start_date: "",
  end_date: "",
  currency: "SGD",
  income: [],
  expenses: [],
  total_income: "0",
  total_expenses: "0",
  net_income: "0",
  trends: [],
};

const EMPTY_ANNUALIZED_INCOME: AnnualizedIncomeResponse = {
  annualized_salary: "0",
  annualized_bonus: "0",
  annualized_dividend: "0",
  annualized_total: "0",
  currency: "SGD",
  as_of: "",
};

function normalizeBalanceSheet(data?: Partial<BalanceSheetResponse> | null): BalanceSheetResponse {
  return {
    ...EMPTY_BALANCE_SHEET,
    ...data,
    assets: data?.assets ?? [],
    liabilities: data?.liabilities ?? [],
    equity: data?.equity ?? [],
    total_assets: data?.total_assets ?? "0",
    total_liabilities: data?.total_liabilities ?? "0",
    total_equity: data?.total_equity ?? "0",
    equation_delta: data?.equation_delta ?? "0",
    currency: data?.currency ?? "SGD",
    as_of_date: data?.as_of_date ?? "",
    is_balanced: data?.is_balanced ?? true,
  };
}

function normalizeIncomeStatement(data?: Partial<IncomeStatementResponse> | null): IncomeStatementResponse {
  return {
    ...EMPTY_INCOME_STATEMENT,
    ...data,
    income: data?.income ?? [],
    expenses: data?.expenses ?? [],
    trends: data?.trends ?? [],
    total_income: data?.total_income ?? "0",
    total_expenses: data?.total_expenses ?? "0",
    net_income: data?.net_income ?? "0",
    currency: data?.currency ?? "SGD",
  };
}

function normalizeAnnualizedIncome(data?: Partial<AnnualizedIncomeResponse> | null): AnnualizedIncomeResponse {
  return {
    ...EMPTY_ANNUALIZED_INCOME,
    ...data,
    annualized_salary: data?.annualized_salary ?? "0",
    annualized_bonus: data?.annualized_bonus ?? "0",
    annualized_dividend: data?.annualized_dividend ?? "0",
    annualized_total: data?.annualized_total ?? "0",
    currency: data?.currency ?? "SGD",
    as_of: data?.as_of ?? "",
  };
}

interface OnboardingStatus {
  accountCount: number;
  statementCount: number;
  approvedStatementCount: number;
  postedEntryCount: number;
}

export default function DashboardPage() {
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheetResponse | null>(null);
  const [incomeStatement, setIncomeStatement] = useState<IncomeStatementResponse | null>(null);
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedTransactionsResponse | null>(null);
  const [recentEntries, setRecentEntries] = useState<JournalEntryListResponse | null>(null);
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null);
  const [annualizedIncome, setAnnualizedIncome] = useState<AnnualizedIncomeResponse | null>(null);
  const [restrictedHoldings, setRestrictedHoldings] = useState<RestrictedHolding[]>([]);
  const [includeRestricted, setIncludeRestricted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trendAccountId, setTrendAccountId] = useState<string | null>(null);
  const [trendAccountName, setTrendAccountName] = useState<string>("Top Asset");

  const fetchData = useCallback(async () => {
    const today = new Date();
    const incomeStart = formatDateInput(new Date(today.getFullYear(), today.getMonth() - 11, 1));
    const incomeEnd = formatDateInput(today);
    setLoading(true);
    try {
      const [
        balanceData,
        incomeData,
        annualizedData,
        restrictedData,
        statsData,
        unmatchedData,
        journalData,
        accountData,
        statementData,
        postedJournalData,
      ] = await Promise.all([
        apiFetch<BalanceSheetResponse>(`/api/reports/balance-sheet?include_restricted=${includeRestricted ? "true" : "false"}`),
        apiFetch<IncomeStatementResponse>(`/api/reports/income-statement?start_date=${incomeStart}&end_date=${incomeEnd}`),
        apiFetch<AnnualizedIncomeResponse>("/api/income/annualized"),
        apiFetch<RestrictedHolding[]>("/api/assets/restricted"),
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
        apiFetch<UnmatchedTransactionsResponse>("/api/reconciliation/unmatched?limit=5"),
        apiFetch<JournalEntryListResponse>("/api/journal-entries?page=1&page_size=5"),
        apiFetch<AccountListResponse>("/api/accounts?limit=1"),
        apiFetch<BankStatementListResponse>("/api/statements"),
        apiFetch<JournalEntryListResponse>("/api/journal-entries?status_filter=posted&limit=1"),
      ]);
      setBalanceSheet(normalizeBalanceSheet(balanceData));
      setIncomeStatement(normalizeIncomeStatement(incomeData));
      setAnnualizedIncome(normalizeAnnualizedIncome(annualizedData));
      setRestrictedHoldings(Array.isArray(restrictedData) ? restrictedData : []);
      setStats(statsData || { total_transactions: 0, matched_transactions: 0, unmatched_transactions: 0, pending_review: 0, auto_accepted: 0, match_rate: 0, score_distribution: {} });
      setUnmatched(unmatchedData || { items: [], total: 0 });
      setRecentEntries(journalData || { items: [], total: 0 });
      setOnboardingStatus({
        accountCount: accountData?.total ?? 0,
        statementCount: statementData?.total ?? 0,
        approvedStatementCount: statementData?.items?.filter((statement) => statement.status === "approved").length ?? 0,
        postedEntryCount: postedJournalData?.total ?? 0,
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard data.");
    } finally {
      setLoading(false);
    }
  }, [includeRestricted]);

  const fetchTrend = useCallback(async () => {
    if (!balanceSheet || !balanceSheet.assets) return;
    const sortedAssets = [...balanceSheet.assets].sort((a, b) => compareAmounts(b.amount, a.amount));
    const target = trendAccountId
      ? sortedAssets.find((a) => a.account_id === trendAccountId) ?? sortedAssets[0]
      : sortedAssets[0];
    if (!target) return;
    setTrendAccountName(target.name);
    try {
      const trendData = await apiFetch<TrendResponse>(`/api/reports/trend?account_id=${target.account_id}&period=monthly`);
      setTrend(trendData);
    } catch (err) {
      console.error("Failed to fetch trend data:", err);
      setTrend(null);
    }
  }, [balanceSheet, trendAccountId]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    if (balanceSheet && balanceSheet.assets) {
      fetchTrend();
    }
  }, [fetchTrend, balanceSheet]);

  const netAssets = useMemo(() => {
    return balanceSheet ? subtractAmounts(balanceSheet.total_assets ?? 0, balanceSheet.total_liabilities ?? 0) : toDecimal("0");
  }, [balanceSheet]);
  const trendPoints = useMemo(() => trend ? trend.points.map((p) => ({ label: formatMonthLabel(p.period_start), value: amountToChartNumber(p.amount) })) : [], [trend]);
  const incomeBars = useMemo(() => incomeStatement && incomeStatement.trends ? incomeStatement.trends.slice(-6).map((t) => ({ label: formatMonthLabel(t.period_start), income: amountToChartNumber(t.total_income), expense: amountToChartNumber(t.total_expenses) })) : [], [incomeStatement]);
  const assetSegments = useMemo(() => {
    if (!balanceSheet || !balanceSheet.assets) return [];
    return balanceSheet.assets
      .filter((a) => compareAmounts(a.amount, "0") > 0)
      .sort((a, b) => compareAmounts(b.amount, a.amount))
      .slice(0, 5)
      .map((a, i) => ({ label: a.name, value: amountToChartNumber(a.amount), color: CHART_PALETTE[i % CHART_PALETTE.length] }));
  }, [balanceSheet]);
  const isCoreFlowComplete = (onboardingStatus?.approvedStatementCount ?? 0) > 0 && (onboardingStatus?.postedEntryCount ?? 0) > 0;
  const showOnboarding = onboardingStatus !== null && !isCoreFlowComplete;
  const onboardingSteps = useMemo(() => {
    const hasAccount = (onboardingStatus?.accountCount ?? 0) > 0;
    const hasStatement = (onboardingStatus?.statementCount ?? 0) > 0;
    const hasApprovedOutput = isCoreFlowComplete;
    return [
      { label: "Add your first account", href: "/accounts", done: hasAccount, Icon: Landmark },
      { label: "Upload a bank statement", href: "/statements", done: hasStatement, Icon: FileText },
      { label: "Review and approve", href: "/review", done: hasApprovedOutput, Icon: BookOpen },
    ];
  }, [isCoreFlowComplete, onboardingStatus]);

  return (
    <div className="p-6">
      <div className="mb-6">
        <UploadToReportHomePanel />
      </div>

      <section className="mb-6" aria-label="Dashboard analytics">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold">Financial analytics</h2>
            <p className="text-sm text-muted">Secondary metrics, charts, and reconciliation details</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/reports/balance-sheet" className="btn-secondary text-sm">Balance Sheet</Link>
            <Link href="/reports/income-statement" className="btn-secondary text-sm">Income Statement</Link>
          </div>
        </div>

        {loading && (
          <div className="card p-5" role="status" aria-label="Dashboard analytics loading">
            <div className="flex items-center gap-2 text-sm text-muted">
              <div className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
              Loading dashboard analytics...
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="card p-5" role="alert" aria-label="Dashboard analytics unavailable">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h3 className="font-semibold">Dashboard analytics unavailable</h3>
                <p className="mt-1 text-sm text-muted">{error}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={fetchData} className="btn-secondary text-sm">Retry analytics</button>
                <Link href="/statements/upload" className="btn-primary text-sm">Upload statements</Link>
              </div>
            </div>
          </div>
        )}

        {!loading && !error && (
          <>
      {showOnboarding && (
        <section className="card p-5 mb-6 border-[var(--accent)]/40" aria-label="Getting started">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs text-muted uppercase tracking-wide">Getting started</p>
              <h2 className="text-lg font-semibold mt-1">Build your first accurate financial view</h2>
              <p className="text-sm text-muted mt-1">Upload, review, and approve a statement to replace this guide with real financial data.</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
              {onboardingSteps.map(({ label, href, done, Icon }) => (
                <Link
                  key={href}
                  href={href}
                  className={`rounded-md border p-3 text-sm transition-colors ${done
                    ? "border-[var(--success)] bg-[var(--success-muted)]"
                    : "border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--accent-muted)]"
                    }`}
                >
                  <div className="flex items-center gap-2">
                    <Icon className={done ? "h-4 w-4 text-[var(--success)]" : "h-4 w-4 text-[var(--accent)]"} aria-hidden="true" />
                    <span className="font-medium">{label}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{done ? "Done" : "Next"}</p>
                </Link>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-4 mb-6">
        <ProcessingSummaryCard />
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Total Assets</p>
          <p className="text-2xl font-semibold text-[var(--success)] mt-1">
            {balanceSheet ? formatCurrencyLocale(balanceSheet.total_assets, balanceSheet.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">As of {balanceSheet?.as_of_date ? formatDateDisplay(balanceSheet.as_of_date) : "—"}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Total Liabilities</p>
          <p className="text-2xl font-semibold text-[var(--error)] mt-1">
            {balanceSheet ? formatCurrencyLocale(balanceSheet.total_liabilities, balanceSheet.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">Obligations</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Net Assets</p>
          <p className="text-2xl font-semibold mt-1">
            {balanceSheet ? formatCurrencyLocale(netAssets, balanceSheet.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">{balanceSheet?.is_balanced ? "✓ Balanced" : "⚠ Drift"}</p>
        </div>
      </div>
      {/* Hero: Net Worth Banner (C2 + C3) */}
      {balanceSheet && (
        <div className="card p-6 mb-6 bg-gradient-to-r from-[var(--accent-muted)] to-[var(--background-card)] border border-[var(--accent)]/30">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Net Worth</p>
              <p className={`text-4xl font-bold ${netAssets.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}>
                {formatCurrencyLocale(netAssets, balanceSheet.currency, "en-US", { maximumFractionDigits: 0 })}
              </p>
              <p className="text-xs text-muted mt-1">As of {balanceSheet?.as_of_date ? formatDateDisplay(balanceSheet.as_of_date) : ""} · {balanceSheet.is_balanced ? "✓ Books balanced" : "⚠ Equation drift"}</p>
              <label className="mt-3 inline-flex items-center gap-2 text-sm text-muted">
                <input
                  type="checkbox"
                  checked={includeRestricted}
                  onChange={(event) => setIncludeRestricted(event.target.checked)}
                  className="rounded"
                />
                Include restricted holdings
              </label>
            </div>
            {stats && (() => {
              const total = stats.total_transactions ?? 0;
              const clean = stats.matched_transactions ?? 0;
              const pct = total > 0 ? Math.round((clean / total) * 100) : 100;
              const barColor = pct >= 85 ? "var(--success)" : pct >= 60 ? "var(--warning)" : "var(--error)";
              return (
                <div className="min-w-[180px]">
                  <div className="flex justify-between text-xs text-muted mb-1">
                    <span>Data health</span>
                    <span className="font-medium" style={{ color: barColor }}>{pct}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                  </div>
                  <div className="flex justify-between text-xs text-muted mt-1">
                    <span>{clean} matched</span>
                    <span>{stats.unmatched_transactions ?? 0} unmatched</span>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Annualized Income</p>
          <p className="text-2xl font-semibold mt-1">
            {annualizedIncome ? formatCurrencyLocale(annualizedIncome.annualized_total, annualizedIncome.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className="text-xs text-muted mt-1">
            As of {annualizedIncome?.as_of ? formatDateDisplay(annualizedIncome.as_of) : "—"}
          </p>
          <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-muted">Salary</p>
              <p className="font-medium">{annualizedIncome ? formatCurrencyLocale(annualizedIncome.annualized_salary, annualizedIncome.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Bonus</p>
              <p className="font-medium">{annualizedIncome ? formatCurrencyLocale(annualizedIncome.annualized_bonus, annualizedIncome.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Dividend</p>
              <p className="font-medium">{annualizedIncome ? formatCurrencyLocale(annualizedIncome.annualized_dividend, annualizedIncome.currency, "en-US", { maximumFractionDigits: 0 }) : "—"}</p>
            </div>
          </div>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">Restricted Holdings</p>
          {restrictedHoldings.length ? (
            <div className="mt-3 space-y-2">
              {restrictedHoldings.map((holding) => (
                <div key={`${holding.ticker}-${holding.unlock_date ?? "locked"}`} className="flex items-center justify-between gap-3 rounded-md bg-[var(--background-muted)] p-3 text-sm">
                  <div>
                    <p className="font-medium">{holding.ticker}</p>
                    <p className="text-xs text-muted" title={holding.vesting_schedule ?? undefined}>
                      Unlock {holding.unlock_date ? formatDateDisplay(holding.unlock_date) : "TBD"}
                    </p>
                  </div>
                  <p className="font-semibold">{formatCurrencyLocale(holding.fair_value, holding.currency, "en-US", { maximumFractionDigits: 0 })}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">No restricted holdings.</p>
          )}
        </div>
      </div>

      {/* This Month KPI Cards */}
      {incomeStatement && incomeStatement.trends && incomeStatement.trends.length > 0 && (() => {
        const latest = incomeStatement.trends[incomeStatement.trends.length - 1];
        const monthIncome = toDecimal(latest.total_income);
        const monthExpense = toDecimal(latest.total_expenses);
        const monthNet = monthIncome.minus(monthExpense);
        const currency = incomeStatement.currency;
        const fmtOpts = { maximumFractionDigits: 0 } as const;
        return (
          <div className="grid gap-4 md:grid-cols-3 mb-6">
            <Link href="/reports/income-statement" className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block">
              <p className="text-xs text-muted uppercase tracking-wide">This Month — Income</p>
              <p className="text-2xl font-semibold text-[var(--success)] mt-1">{formatCurrencyLocale(monthIncome, currency, "en-US", fmtOpts)}</p>
              <p className="text-xs text-muted mt-1">{formatMonthLabel(latest.period_start)}</p>
            </Link>
            <Link href="/reports/income-statement" className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block">
              <p className="text-xs text-muted uppercase tracking-wide">This Month — Expenses</p>
              <p className="text-2xl font-semibold text-[var(--error)] mt-1">{formatCurrencyLocale(monthExpense, currency, "en-US", fmtOpts)}</p>
              <p className="text-xs text-muted mt-1">Total outflows</p>
            </Link>
            <Link href="/reports/income-statement" className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block">
              <p className="text-xs text-muted uppercase tracking-wide">This Month — Net</p>
              <p className={`text-2xl font-semibold mt-1 ${monthNet.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}>{formatCurrencyLocale(monthNet, currency, "en-US", fmtOpts)}</p>
              <p className="text-xs text-muted mt-1">{monthNet.isNegative() ? "Deficit" : "Surplus"}</p>
            </Link>
          </div>
        );
      })()}


      {/* Charts Row */}
      <div className="mb-6">
        <NetWorthTimeSeriesChart />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <div className="card p-5">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-muted uppercase tracking-wide">Asset Trend</p>
            {balanceSheet && balanceSheet.assets && balanceSheet.assets.length > 1 && (
              <select
                value={trendAccountId ?? ""}
                onChange={(e) => setTrendAccountId(e.target.value || null)}
                className="input text-xs py-1 px-2 w-auto"
              >
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
            <Link href="/reconciliation" className="flex justify-between p-3 rounded-md bg-[var(--success-muted)] text-sm hover:ring-1 hover:ring-[var(--success)] transition-all">
              <span>Auto accepted</span><span className="font-semibold">{stats?.auto_accepted ?? 0}</span>
            </Link>
            <Link href="/reconciliation/review-queue" className="flex justify-between p-3 rounded-md bg-[var(--warning-muted)] text-sm hover:ring-1 hover:ring-[var(--warning)] transition-all">
              <span>Pending review</span><span className="font-semibold">{stats?.pending_review ?? 0}</span>
            </Link>
            <Link href="/reconciliation/unmatched" className="flex justify-between p-3 rounded-md bg-[var(--error-muted)] text-sm hover:ring-1 hover:ring-[var(--error)] transition-all">
              <span>Unmatched</span><span className="font-semibold">{stats?.unmatched_transactions ?? 0}</span>
            </Link>
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
                <span className="font-semibold">{balanceSheet ? formatCurrencyLocale(t.amount, balanceSheet.currency, "en-US", { maximumFractionDigits: 0 }) : t.amount}</span>
              </div>
            )) : <p className="text-sm text-muted">No unmatched transactions.</p>}
            <Link href="/reconciliation/unmatched" className="text-sm text-[var(--warning)] hover:underline inline-flex items-center gap-1">
              Review unmatched →
            </Link>
          </div>
        </div>
      </div>
          </>
        )}
      </section>
    </div>
  );
}
