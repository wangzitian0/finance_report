"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { useBaseCurrency } from "@/hooks/useBaseCurrency";
import { useCurrencies } from "@/hooks/useCurrencies";
import { REPORT_PERIOD_PRESETS, type UseReportFiltersResult } from "@/hooks/useReportFilters";
import { formatDateDisplay } from "@/lib/date";

/**
 * The dimension bar of Home and of every `/reports` tab (#2621 LC, #2548 P1).
 *
 * One bar sets the period preset, steps to the previous or next period, sets a custom period,
 * and sets the currency. `showScope` adds the restricted-holdings scope where a balance sheet shows.
 * The bar writes only the URL (`useReportFilters`), so a link reproduces the view.
 */
export function ReportDimensionBar({
  filters,
  showScope = false,
}: {
  filters: UseReportFiltersResult;
  showScope?: boolean;
}) {
  const { currencies } = useCurrencies();
  const { baseCurrency } = useBaseCurrency();
  const currency = filters.currency ?? baseCurrency;
  const currencyChoices = currencies.includes(currency) ? currencies : [currency, ...currencies];
  const stepClass =
    "inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-muted hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div role="group" aria-label="Report dimensions" className="flex flex-wrap items-center gap-2 text-sm">
      <div role="group" aria-label="Reporting period" className="inline-flex items-center gap-0.5 rounded-lg bg-[var(--background-muted)] p-1">
        {REPORT_PERIOD_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-label={`Period ${preset}`}
            aria-pressed={filters.preset === preset}
            onClick={() => filters.setPreset(preset)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              filters.preset === preset
                ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                : "text-muted hover:text-[var(--foreground)]"
            }`}
          >
            {preset}
          </button>
        ))}
        <button
          type="button"
          aria-label="Custom period"
          aria-pressed={filters.preset === null}
          onClick={() => filters.setCustomPeriod(filters.startDate, filters.endDate)}
          className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
            filters.preset === null
              ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
              : "text-muted hover:text-[var(--foreground)]"
          }`}
        >
          Custom
        </button>
      </div>
      {filters.preset === null ? (
        <div className="inline-flex items-center gap-1">
          <input
            type="date"
            aria-label="Period start"
            value={filters.startDate}
            max={filters.endDate}
            onChange={(event) => {
              const start = event.target.value;
              if (start) filters.setCustomPeriod(start, start > filters.endDate ? start : filters.endDate);
            }}
            className="input h-8 w-auto py-0 text-xs"
          />
          <span aria-hidden="true" className="text-muted">–</span>
          <input
            type="date"
            aria-label="Period end"
            value={filters.endDate}
            min={filters.startDate}
            onChange={(event) => {
              const end = event.target.value;
              if (end) filters.setCustomPeriod(end < filters.startDate ? end : filters.startDate, end);
            }}
            className="input h-8 w-auto py-0 text-xs"
          />
        </div>
      ) : (
        <div className="inline-flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous period"
            disabled={filters.previousEnd === null}
            onClick={() => filters.goToPeriodEnd(filters.previousEnd!)}
            className={stepClass}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <span data-testid="report-period-range" aria-live="polite" className="min-w-[11rem] text-center text-xs font-medium tabular-nums">
            {`${formatDateDisplay(filters.startDate)} – ${formatDateDisplay(filters.endDate)}`}
          </span>
          <button
            type="button"
            aria-label="Next period"
            disabled={filters.nextEnd === null}
            onClick={() => filters.goToPeriodEnd(filters.nextEnd!)}
            className={stepClass}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}
      <select
        aria-label="Reporting currency"
        value={currency}
        onChange={(event) => filters.setCurrency(event.target.value)}
        className="input h-8 w-auto py-0 text-xs"
      >
        {currencyChoices.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </select>
      {showScope && (
        <label className="inline-flex items-center gap-1.5 text-xs text-muted">
          <input
            type="checkbox"
            checked={filters.includeRestricted}
            onChange={(event) => filters.setIncludeRestricted(event.target.checked)}
          />
          Include restricted holdings
        </label>
      )}
    </div>
  );
}
