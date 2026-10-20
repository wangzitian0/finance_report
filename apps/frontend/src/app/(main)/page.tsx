"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { UploadToReportHomePanel } from "@/components/workflow/WorkflowNotifications";
import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { TrustMeter } from "@/components/home/TrustMeter";
import {
  ThreeStatementNav,
  type CockpitPeriodPreset,
} from "@/components/home/ThreeStatementNav";
import { HomeAnalyticsSection } from "@/components/home/HomeAnalyticsSection";

import { formatMonthLabel } from "@/lib/date";
import {
  amountToChartNumber,
  compareAmounts,
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
  const [periodPreset, setPeriodPreset] = useState<CockpitPeriodPreset>("1Y");
  const [selectedCurrency, setSelectedCurrency] = useState<string>("");

  // Slice 3 of #751: dashboard aggregation + normalization live in the hook
  // layer; the route composes the returned data.
  const {
    balanceSheet,
    incomeStatement,
    annualizedIncome,
    restrictedHoldings,
    stats,
    statements,
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
  } = useDashboardData(
    includeRestricted,
    periodPreset,
    selectedCurrency || undefined,
  );

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

  const incomeBars = useMemo(() => {
    if (!incomeStatement || !incomeStatement.trends) return [];
    const sliceLimit =
      periodPreset === "1M"
        ? 1
        : periodPreset === "1Q"
          ? 3
          : periodPreset === "1Y" || periodPreset === "YTD"
            ? 12
            : periodPreset === "3Y"
              ? 36
              : incomeStatement.trends.length;
    return incomeStatement.trends.slice(-Math.max(sliceLimit, 1)).map((t) => ({
      label: formatMonthLabel(t.period_start),
      income: amountToChartNumber(t.total_income),
      expense: amountToChartNumber(t.total_expenses),
    }));
  }, [incomeStatement, periodPreset]);

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
      {/* EPIC-022 AC22.21.6: the three statements are the product — lead with a
          segmented entry into each, deep-linking to the full report. */}
      <div className="mb-4">
        <ThreeStatementNav
          balanceSheet={balanceSheet}
          incomeStatement={incomeStatement}
          periodPreset={periodPreset}
          onPeriodPresetChange={setPeriodPreset}
          includeRestricted={includeRestricted}
          onIncludeRestrictedChange={setIncludeRestricted}
          onCurrencyChange={setSelectedCurrency}
          onboardingStatus={onboardingStatus}
        />
      </div>

      <div className="mb-4">
        <UploadToReportHomePanel />
      </div>

      <div className="mb-4">
        <TrustMeter
          statements={loading ? null : statements}
          stats={stats}
        />
      </div>

      {advisorSuggestions.length > 0 ? (
        <div className="mb-4">
          <AdvisorBrief suggestions={advisorSuggestions} />
        </div>
      ) : null}

      <section className="mb-6" aria-label="Dashboard analytics">
        {loading && (
          <div
            className="card p-4"
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
            className="card p-4"
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
            annualizedIncome={annualizedIncome}
            restrictedHoldings={restrictedHoldings}
          />
        )}
      </section>
    </div>
  );
}
