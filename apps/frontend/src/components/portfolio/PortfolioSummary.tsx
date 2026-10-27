"use client";

import { compareAmounts, formatCurrencyLocale } from "@/lib/audit/money";
import { computeMarketValuePerformance } from "@/lib/portfolioPerformance";
import {
  formatSignedPercentFromPercentValue,
  formatPercentFromPercentValue,
  percentNumberFromPercentValue,
} from "@/lib/audit/ratio/format";
import type { InvestmentPerformanceReportSchedule } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { apiOperation } from "@/lib/api-client";
import { AllocationBreakdown } from "@/lib/types";
import { PieChart } from "@/components/charts/PieChart";

function amountClass(value: string | null): string {
  if (value === null) return "text-muted";
  const comparison = compareAmounts(value, "0");
  if (comparison === 0) return "";
  return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

interface PerformanceCardProps {
  schedule?: InvestmentPerformanceReportSchedule;
  isLoading?: boolean;
  error?: unknown;
}

/**
 * The asset-dashboard performance answer (#914): unrealized market-value
 * gain/loss, a simple return on cost for the schedule period, and a
 * price-freshness flag. TWR/IRR/MWR stay on the reporting side and are not
 * presented here as the headline answer.
 */
export function PerformanceCard({
  schedule,
  isLoading = false,
  error = null,
}: PerformanceCardProps) {
  if (isLoading) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          Performance
        </p>
        <div className="flex items-center justify-center py-4">
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin text-muted" />
        </div>
      </div>
    );
  }

  if (error || !schedule) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          Performance
        </p>
        <p className="text-sm text-muted">Unable to load performance metrics</p>
      </div>
    );
  }

  const performance = computeMarketValuePerformance(schedule);
  const freshness = schedule.data_freshness;

  return (
    <div className="card p-5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs text-muted uppercase tracking-wide">
          Market-Value Performance
        </p>
        <span
          className={`text-xs ${freshness.stale ? "text-[var(--error)]" : "text-muted"}`}
          title={
            freshness.latest_price_date
              ? `Latest price ${freshness.latest_price_date}`
              : undefined
          }
        >
          {freshness.stale ? "Prices stale" : "Prices current"}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-muted">Unrealized gain/loss</p>
          <p
            className={`text-xl font-semibold mt-0.5 ${amountClass(performance.unrealizedPnl)}`}
          >
            {formatCurrencyLocale(performance.unrealizedPnl, schedule.currency)}
          </p>
          <p className="text-xs text-muted mt-0.5">
            vs cost{" "}
            {formatCurrencyLocale(
              performance.totalCostBasis,
              schedule.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Return on cost</p>
          <p
            className={`text-xl font-semibold mt-0.5 ${amountClass(performance.returnOnCostPercent)}`}
          >
            {formatSignedPercentFromPercentValue(
              performance.returnOnCostPercent,
            )}
          </p>
          <p className="text-xs text-muted mt-0.5">
            as of {schedule.as_of_date}
          </p>
        </div>
      </div>
    </div>
  );
}

const CHART_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

type AllocationType = "sector" | "geography" | "asset-class";

const ALLOCATION_OPERATIONS = {
  sector: "get_sector_allocation_portfolio_allocation_sector_get",
  geography: "get_geography_allocation_portfolio_allocation_geography_get",
  "asset-class":
    "get_asset_class_allocation_portfolio_allocation_asset_class_get",
} as const;

interface AllocationChartProps {
  type: AllocationType;
  title: string;
}

const LABELS: Record<AllocationType, string> = {
  sector: "Sector",
  geography: "Geography",
  "asset-class": "Asset Class",
};

export function AllocationChart({ type, title }: AllocationChartProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio-allocation", type],
    queryFn: () => apiOperation(ALLOCATION_OPERATIONS[type]),
  });

  if (isLoading) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <div className="flex items-center justify-center py-8">
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin text-muted" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <p className="text-sm text-muted">Unable to load allocation data</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <p className="text-sm text-muted">No allocation data available</p>
      </div>
    );
  }

  const segments = data.map((d, i) => ({
    label: d.category || "Unknown",
    value: percentNumberFromPercentValue(d.percentage, { fallback: 0 }) ?? 0,
    color: CHART_PALETTE[i % CHART_PALETTE.length],
  }));

  return (
    <div className="card p-5">
      <p className="text-xs text-muted uppercase tracking-wide mb-3">{title}</p>
      <PieChart segments={segments} centerLabel={LABELS[type]} />
      <div className="mt-4 space-y-1.5">
        {data.map((d, i) => (
          <div
            key={d.category}
            className="flex items-center justify-between text-sm"
          >
            <div className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{
                  backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length],
                }}
              />
              <span className="truncate">{d.category || "Unknown"}</span>
              <span className="text-xs text-muted">({d.count})</span>
            </div>
            <span className="font-medium">
              {formatPercentFromPercentValue(d.percentage, { dp: 1 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
