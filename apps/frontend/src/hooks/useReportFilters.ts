"use client";

import { useCallback, useMemo, useState } from "react";

import { formatDateInput } from "@/lib/date";

/**
 * Query-layer hook for report routes (Slice 3 of #751).
 *
 * Owns the shared date + currency filter state for a report page and derives the
 * API query string, CSV export path, and AI-prompt text. This keeps report
 * routes thin: they express page-level intent and read the derived values
 * instead of re-implementing URLSearchParams / export-path / prompt boilerplate.
 *
 * Two filter shapes are supported, matching the existing report endpoints:
 *  - point-in-time reports (balance sheet) use a single `as_of_date`;
 *  - range reports (income statement, cash flow) use `start_date`/`end_date`.
 */

export type ReportType = "balance-sheet" | "income-statement" | "cash-flow";

interface UseReportFiltersOptions {
  reportType: ReportType;
  initialAsOfDate?: string;
  initialStartDate?: string;
  initialEndDate?: string;
  initialCurrency?: string;
}

export interface UseReportFiltersResult {
  asOfDate: string;
  startDate: string;
  endDate: string;
  currency: string;
  setAsOfDate: (value: string) => void;
  setStartDate: (value: string) => void;
  setEndDate: (value: string) => void;
  setCurrency: (value: string) => void;
  /** Encoded API query string (without a leading `?`). */
  queryString: string;
  /** Authenticated CSV export path for this report + current filters. */
  exportPath: string;
}

const today = () => formatDateInput(new Date());

export function useReportFilters(
  options: UseReportFiltersOptions,
): UseReportFiltersResult {
  const { reportType } = options;
  const isPointInTime = reportType === "balance-sheet";

  const [asOfDate, setAsOfDate] = useState(options.initialAsOfDate ?? today());
  const [startDate, setStartDate] = useState(options.initialStartDate ?? today());
  const [endDate, setEndDate] = useState(options.initialEndDate ?? today());
  const [currency, setCurrency] = useState(options.initialCurrency ?? "SGD");

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (isPointInTime) {
      params.set("as_of_date", asOfDate);
    } else {
      params.set("start_date", startDate);
      params.set("end_date", endDate);
    }
    params.set("currency", currency);
    return params.toString();
  }, [asOfDate, currency, endDate, isPointInTime, startDate]);

  const exportPath = useMemo(
    () => `/api/reports/export?report_type=${reportType}&format=csv&${queryString}`,
    [queryString, reportType],
  );

  return {
    asOfDate,
    startDate,
    endDate,
    currency,
    setAsOfDate: useCallback((value: string) => setAsOfDate(value), []),
    setStartDate: useCallback((value: string) => setStartDate(value), []),
    setEndDate: useCallback((value: string) => setEndDate(value), []),
    setCurrency: useCallback((value: string) => setCurrency(value), []),
    queryString,
    exportPath,
  };
}
