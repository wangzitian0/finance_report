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
import { formatCompactChartValue } from "@/components/charts/BarChart";

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

const UNCLASSIFIED_LABELS: Record<AllocationType, string> = {
  sector: "Unclassified sector",
  geography: "Unclassified geography",
  "asset-class": "Unclassified asset class",
};

export function formatAllocationCategory(
  category: string | null | undefined,
  type: AllocationType,
): string {
  const trimmed = category?.trim() ?? "";
  if (!trimmed || trimmed.toLowerCase() === "unknown") {
    return UNCLASSIFIED_LABELS[type];
  }
  return trimmed;
}

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
    label: formatAllocationCategory(d.category, type),
    value: percentNumberFromPercentValue(d.percentage, { fallback: 0 }) ?? 0,
    color: CHART_PALETTE[i % CHART_PALETTE.length],
  }));

  return (
    <div className="card p-5">
      <p className="text-xs text-muted uppercase tracking-wide mb-3">{title}</p>
      <PieChart
        segments={segments}
        centerLabel={LABELS[type]}
        showLegend={false}
      />
      <div className="mt-4 space-y-1.5">
        {data.map((d, i) => {
          const categoryLabel = formatAllocationCategory(d.category, type);
          return (
            <div
              key={`${d.category}-${i}`}
              className="flex items-center justify-between text-sm"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{
                    backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length],
                  }}
                />
                <span className="truncate">{categoryLabel}</span>
                <span className="text-xs text-muted">({d.count})</span>
              </div>
              <span className="font-medium">
                {formatPercentFromPercentValue(d.percentage, { dp: 1 })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface PieSegment {
  label: string;
  value: number;
  color: string;
}

interface PieChartProps {
  segments: PieSegment[];
  size?: number;
  centerLabel?: string;
  showLegend?: boolean;
}

const DEFAULT_SIZE = 180;

export function PieChart({
  segments,
  size = DEFAULT_SIZE,
  centerLabel = "Assets",
  showLegend = true,
}: PieChartProps) {
  const filtered = segments.filter((segment) => segment.value > 0);
  const total = filtered.reduce((sum, segment) => sum + segment.value, 0);
  const radius = 60;
  const circumference = 2 * Math.PI * radius;

  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 160 160" role="img" aria-label="Pie chart">
        <g transform="translate(80,80)">
          {filtered.map((segment) => {
            const fraction = total ? segment.value / total : 0;
            const dash = fraction * circumference;
            const dashArray = `${dash} ${circumference - dash}`;
            const dashOffset = offset;
            offset -= dash;
            return (
              <circle
                key={segment.label}
                r={radius}
                fill="transparent"
                stroke={segment.color}
                strokeWidth="18"
                strokeDasharray={dashArray}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
              />
            );
          })}
          <circle r="42" fill="var(--background-card)" />
        </g>
        <text
          x="80"
          y="80"
          textAnchor="middle"
          dominantBaseline="middle"
          className="text-xs font-semibold"
          style={{ fill: "var(--foreground)" }}
        >
          {centerLabel}
        </text>
      </svg>
      {showLegend ? (
        <div className="grid w-full grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-[var(--foreground-muted)]">
          {filtered.map((segment) => {
            const pct = total > 0 ? Math.round((segment.value / total) * 100) : 0;
            return (
              <div key={segment.label} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 bg-[var(--background-muted)]/50">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: segment.color }}
                  />
                  <span className="truncate">{segment.label}</span>
                </div>
                <span
                  className="shrink-0 font-medium text-[var(--foreground)]"
                  data-testid={`pie-segment-share-${segment.label}`}
                >
                  {`${pct}% · ${formatCompactChartValue(segment.value)}`}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
      <table className="sr-only">
        <caption>Chart data</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td>{item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
