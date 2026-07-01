"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { FileText, BookOpen, BarChart3 } from "lucide-react";
import ProcessingSummaryCard from "@/components/ProcessingSummaryCard";
import { UploadToReportHomePanel } from "@/components/workflow/WorkflowNotifications";
import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { TrustMeter } from "@/components/home/TrustMeter";
import { ThreeStatementNav } from "@/components/home/ThreeStatementNav";
import { InfoHint } from "@/components/ui/InfoHint";
import { OpeningBalanceWarningBanner } from "@/components/reports/OpeningBalanceWarningBanner";

import { formatDateDisplay, formatMonthLabel } from "@/lib/date";
import {
  amountToChartNumber,
  compareAmounts,
  formatCurrencyLocale,
  subtractAmounts,
  toDecimal,
} from "@/lib/audit/money";
import { percentNumberFromParts } from "@/lib/audit/ratio/format";
import { useDashboardData } from "@/hooks/useDashboardData";
import { BarChart } from "@/components/charts/BarChart";
import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { PieChart } from "@/components/charts/PieChart";
import { TrendChart } from "@/components/charts/TrendChart";

const CHART_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export default function HomePage() {
  const [includeRestricted, setIncludeRestricted] = useState(false);
  // EPIC-022 PR4: Home defaults to a lean view; heavy charts are opt-in.
  const [showAnalytics, setShowAnalytics] = useState(false);

  // Slice 3 of #751: dashboard aggregation + normalization live in the hook
  // layer; the route composes the returned data.
  const {
    balanceSheet,
    incomeStatement,
    annualizedIncome,
    restrictedHoldings,
    stats,
    unmatched,
    recentEntries,
    onboardingStatus,
    advisorSuggestions,
    trend,
    trendAccountName,
    trendAccountId,
    setTrendAccountId,
    loading,
    error,
    retry: fetchData,
  } = useDashboardData(includeRestricted);

  const netAssets = useMemo(() => {
    return balanceSheet
      ? subtractAmounts(
          balanceSheet.total_assets ?? 0,
          balanceSheet.total_liabilities ?? 0,
        )
      : toDecimal("0");
  }, [balanceSheet]);
  const trendPoints = useMemo(
    () =>
      trend
        ? trend.points.map((p) => ({
            label: formatMonthLabel(p.period_start),
            value: amountToChartNumber(p.amount),
          }))
        : [],
    [trend],
  );
  const incomeBars = useMemo(
    () =>
      incomeStatement && incomeStatement.trends
        ? incomeStatement.trends
            .slice(-6)
            .map((t) => ({
              label: formatMonthLabel(t.period_start),
              income: amountToChartNumber(t.total_income),
              expense: amountToChartNumber(t.total_expenses),
            }))
        : [],
    [incomeStatement],
  );
  const assetSegments = useMemo(() => {
    if (!balanceSheet || !balanceSheet.assets) return [];
    return balanceSheet.assets
      .filter((a) => compareAmounts(a.amount, "0") > 0)
      .sort((a, b) => compareAmounts(b.amount, a.amount))
      .slice(0, 5)
      .map((a, i) => ({
        label: a.name,
        value: amountToChartNumber(a.amount),
        color: CHART_PALETTE[i % CHART_PALETTE.length],
      }));
  }, [balanceSheet]);
  const isCoreFlowComplete =
    (onboardingStatus?.approvedStatementCount ?? 0) > 0 &&
    (onboardingStatus?.postedEntryCount ?? 0) > 0;
  const showOnboarding = onboardingStatus !== null && !isCoreFlowComplete;
  // EPIC-022 AC22.16.1 (#1116): onboarding points only at everyday surfaces —
  // the first step is Upload, not the accounting-jargon "/accounts" route.
  const onboardingSteps = useMemo(() => {
    const hasStatement = (onboardingStatus?.statementCount ?? 0) > 0;
    const hasApprovedOutput = isCoreFlowComplete;
    return [
      {
        label: "Upload a bank statement",
        href: "/upload",
        done: hasStatement,
        Icon: FileText,
      },
      {
        label: "Review and approve",
        href: "/notifications",
        done: hasApprovedOutput,
        Icon: BookOpen,
      },
      {
        label: "Read your reports",
        href: "/reports",
        done: hasApprovedOutput,
        Icon: BarChart3,
      },
    ];
  }, [isCoreFlowComplete, onboardingStatus]);

  return (
    <div className="p-6">
      <div className="mb-6">
        <UploadToReportHomePanel />
      </div>

      {/* EPIC-022 AC22.21.6: the three statements are the product — lead with a
          segmented entry into each, deep-linking to the full report. */}
      <div className="mb-6">
        <ThreeStatementNav />
      </div>

      <div className="mb-6">
        <TrustMeter />
      </div>

      {advisorSuggestions.length > 0 ? (
        <div className="mb-6">
          <AdvisorBrief suggestions={advisorSuggestions} />
        </div>
      ) : null}

      <section className="mb-6" aria-label="Dashboard analytics">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold">Financial analytics</h2>
            <p className="text-sm text-muted">
              Secondary metrics, charts, and reconciliation details
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/reports/balance-sheet"
              className="btn-secondary text-sm"
            >
              Balance Sheet
            </Link>
            <Link
              href="/reports/income-statement"
              className="btn-secondary text-sm"
            >
              Income Statement
            </Link>
          </div>
        </div>

        {loading && (
          <div
            className="card p-5"
            role="status"
            aria-label="Dashboard analytics loading"
          >
            <div className="flex items-center gap-2 text-sm text-muted">
              <div className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
              Loading dashboard analytics...
            </div>
          </div>
        )}

        {!loading && error && (
          <div
            className="card p-5"
            role="alert"
            aria-label="Dashboard analytics unavailable"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h3 className="font-semibold">
                  Dashboard analytics unavailable
                </h3>
                <p className="mt-1 text-sm text-muted">{error}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={fetchData} className="btn-secondary text-sm">
                  Retry analytics
                </button>
                <Link href="/upload" className="btn-primary text-sm">
                  Upload statements
                </Link>
              </div>
            </div>
          </div>
        )}

        {!loading && !error && (
          <>
            {showOnboarding && (
              <section
                className="card p-5 mb-6 border-[var(--accent)]/40"
                aria-label="Getting started"
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wide">
                      Getting started
                    </p>
                    <h2 className="text-lg font-semibold mt-1">
                      Build your first accurate financial view
                    </h2>
                    <p className="text-sm text-muted mt-1">
                      Upload, review, and approve a statement to replace this
                      guide with real financial data.
                    </p>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
                    {onboardingSteps.map(({ label, href, done, Icon }) => (
                      <Link
                        key={href}
                        href={href}
                        className={`rounded-md border p-3 text-sm transition-colors ${
                          done
                            ? "border-[var(--success)] bg-[var(--success-muted)]"
                            : "border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--accent-muted)]"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <Icon
                            className={
                              done
                                ? "h-4 w-4 text-[var(--success)]"
                                : "h-4 w-4 text-[var(--accent)]"
                            }
                            aria-hidden="true"
                          />
                          <span className="font-medium">{label}</span>
                        </div>
                        <p className="mt-1 text-xs text-muted">
                          {done ? "Done" : "Next"}
                        </p>
                      </Link>
                    ))}
                  </div>
                </div>
              </section>
            )}

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

            <div className="grid gap-4 lg:grid-cols-2 mb-6">
              <div className="card p-5">
                <p className="text-xs text-muted uppercase tracking-wide">
                  Annualized Income
                </p>
                <p className="text-2xl font-semibold mt-1">
                  {annualizedIncome
                    ? formatCurrencyLocale(
                        annualizedIncome.annualized_total,
                        annualizedIncome.currency,
                        "en-US",
                        { maximumFractionDigits: 0 },
                      )
                    : "—"}
                </p>
                <p className="text-xs text-muted mt-1">
                  As of{" "}
                  {annualizedIncome?.as_of
                    ? formatDateDisplay(annualizedIncome.as_of)
                    : "—"}
                </p>
                <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-muted">Salary</p>
                    <p className="font-medium">
                      {annualizedIncome
                        ? formatCurrencyLocale(
                            annualizedIncome.annualized_salary,
                            annualizedIncome.currency,
                            "en-US",
                            { maximumFractionDigits: 0 },
                          )
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Bonus</p>
                    <p className="font-medium">
                      {annualizedIncome
                        ? formatCurrencyLocale(
                            annualizedIncome.annualized_bonus,
                            annualizedIncome.currency,
                            "en-US",
                            { maximumFractionDigits: 0 },
                          )
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Dividend</p>
                    <p className="font-medium">
                      {annualizedIncome
                        ? formatCurrencyLocale(
                            annualizedIncome.annualized_dividend,
                            annualizedIncome.currency,
                            "en-US",
                            { maximumFractionDigits: 0 },
                          )
                        : "—"}
                    </p>
                  </div>
                </div>
              </div>
              <div className="card p-5">
                <p className="text-xs text-muted uppercase tracking-wide">
                  Restricted Holdings
                </p>
                {restrictedHoldings.length ? (
                  <div className="mt-3 space-y-2">
                    {restrictedHoldings.map((holding) => (
                      <div
                        key={`${holding.ticker}-${holding.unlock_date ?? "locked"}`}
                        className="flex items-center justify-between gap-3 rounded-md bg-[var(--background-muted)] p-3 text-sm"
                      >
                        <div>
                          <p className="font-medium">{holding.ticker}</p>
                          <p
                            className="text-xs text-muted"
                            title={holding.vesting_schedule ?? undefined}
                          >
                            Unlock{" "}
                            {holding.unlock_date
                              ? formatDateDisplay(holding.unlock_date)
                              : "TBD"}
                          </p>
                        </div>
                        <p className="font-semibold">
                          {formatCurrencyLocale(
                            holding.fair_value,
                            holding.currency,
                            "en-US",
                            { maximumFractionDigits: 0 },
                          )}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-muted">
                    No restricted holdings.
                  </p>
                )}
              </div>
            </div>

            {/* This Month KPI Cards */}
            {incomeStatement &&
              incomeStatement.trends &&
              incomeStatement.trends.length > 0 &&
              (() => {
                const latest =
                  incomeStatement.trends[incomeStatement.trends.length - 1];
                const monthIncome = toDecimal(latest.total_income);
                const monthExpense = toDecimal(latest.total_expenses);
                const monthNet = monthIncome.minus(monthExpense);
                const currency = incomeStatement.currency;
                const fmtOpts = { maximumFractionDigits: 0 } as const;
                return (
                  <div className="grid gap-4 md:grid-cols-3 mb-6">
                    <Link
                      href="/reports/income-statement"
                      className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
                    >
                      <p className="text-xs text-muted uppercase tracking-wide">
                        This Month — Income
                      </p>
                      <p className="text-2xl font-semibold text-[var(--success)] mt-1">
                        {formatCurrencyLocale(
                          monthIncome,
                          currency,
                          "en-US",
                          fmtOpts,
                        )}
                      </p>
                      <p className="text-xs text-muted mt-1">
                        {formatMonthLabel(latest.period_start)}
                      </p>
                    </Link>
                    <Link
                      href="/reports/income-statement"
                      className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
                    >
                      <p className="text-xs text-muted uppercase tracking-wide">
                        This Month — Expenses
                      </p>
                      <p className="text-2xl font-semibold text-[var(--error)] mt-1">
                        {formatCurrencyLocale(
                          monthExpense,
                          currency,
                          "en-US",
                          fmtOpts,
                        )}
                      </p>
                      <p className="text-xs text-muted mt-1">Total outflows</p>
                    </Link>
                    <Link
                      href="/reports/income-statement"
                      className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
                    >
                      <p className="text-xs text-muted uppercase tracking-wide">
                        This Month — Net
                      </p>
                      <p
                        className={`text-2xl font-semibold mt-1 ${monthNet.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}
                      >
                        {formatCurrencyLocale(
                          monthNet,
                          currency,
                          "en-US",
                          fmtOpts,
                        )}
                      </p>
                      <p className="text-xs text-muted mt-1">
                        {monthNet.isNegative() ? "Deficit" : "Surplus"}
                      </p>
                    </Link>
                  </div>
                );
              })()}

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
                            onChange={(e) =>
                              setTrendAccountId(e.target.value || null)
                            }
                            className="input text-xs py-1 px-2 w-auto"
                          >
                            <option value="">Top Asset</option>
                            {[...balanceSheet.assets]
                              .sort((a, b) =>
                                compareAmounts(b.amount, a.amount),
                              )
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
                    <h3 className="font-semibold mt-1 mb-4">
                      Monthly comparison
                    </h3>
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
        )}
      </section>
    </div>
  );
}
