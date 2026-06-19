"use client";

import { compareAmounts, formatCurrencyLocale } from "@/lib/money";
import { computeMarketValuePerformance } from "@/lib/portfolioPerformance";
import { formatSignedPercentFromPercentValue } from "@/lib/ratio/format";
import type { InvestmentPerformanceReportSchedule } from "@/lib/types";

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
