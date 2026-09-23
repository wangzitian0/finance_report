"use client";

import { useSearchParams } from "next/navigation";
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

  // Seed initial filter state with precedence:
  //   URL query param ?? explicit option ?? existing default.
  // This preserves deep-link support (e.g. ?start_date=2025-01-01&end_date=2025-01-31&currency=SGD)
  // so external links, bookmarks, and date range filters take precedence over caller
  // default configs (such as defaultStartDate()), avoiding inverted start/end date errors.
  // `useSearchParams` is read once; the values only seed `useState` initial expressions
  // (evaluated on mount), so they never fight user edits and no URL round-trip / router.replace
  // is performed here.
  const searchParams = useSearchParams();
  const initialAsOfDate =
    searchParams.get("as_of_date") ?? options.initialAsOfDate ?? today();
  const initialStartDate =
    searchParams.get("start_date") ?? options.initialStartDate ?? today();
  const initialEndDate =
    searchParams.get("end_date") ?? options.initialEndDate ?? today();
  const initialCurrency =
    searchParams.get("currency") ?? options.initialCurrency ?? "SGD";


  const [asOfDate, setAsOfDate] = useState(initialAsOfDate);
  const [startDate, setStartDate] = useState(initialStartDate);
  const [endDate, setEndDate] = useState(initialEndDate);
  const [currency, setCurrency] = useState(initialCurrency);

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
