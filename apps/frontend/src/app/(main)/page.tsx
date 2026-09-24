"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { UploadToReportHomePanel } from "@/components/workflow/WorkflowNotifications";
import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { TrustMeter } from "@/components/home/TrustMeter";
import { ThreeStatementNav } from "@/components/home/ThreeStatementNav";
import { OnboardingGuideCard } from "@/components/home/OnboardingGuideCard";
import { HomeNetWorthBanner } from "@/components/home/HomeNetWorthBanner";
import { HomeIncomeCards } from "@/components/home/HomeIncomeCards";
import { HomeAnalyticsSection } from "@/components/home/HomeAnalyticsSection";

import { formatMonthLabel } from "@/lib/date";
import {
  amountToChartNumber,
  compareAmounts,
  subtractAmounts,
  toDecimal,
} from "@/lib/audit/money";
import { useDashboardData } from "@/hooks/useDashboardData";

const CHART_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export default function HomePage() {
  const [includeRestricted, setIncludeRestricted] = useState(false);

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
            <OnboardingGuideCard onboardingStatus={onboardingStatus} />

            <HomeNetWorthBanner
              balanceSheet={balanceSheet}
              netAssets={netAssets}
              includeRestricted={includeRestricted}
              setIncludeRestricted={setIncludeRestricted}
              stats={stats}
            />

            <HomeIncomeCards
              annualizedIncome={annualizedIncome}
              restrictedHoldings={restrictedHoldings}
              incomeStatement={incomeStatement}
            />

            <HomeAnalyticsSection
              balanceSheet={balanceSheet}
              stats={stats}
              recentEntries={recentEntries}
              unmatched={unmatched}
              trend={trend}
              trendAccountName={trendAccountName}
              trendAccountId={trendAccountId}
              setTrendAccountId={setTrendAccountId}
              trendPoints={trendPoints}
              assetSegments={assetSegments}
              incomeBars={incomeBars}
            />
          </>
        )}
      </section>
    </div>
  );
}
