import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReportFilters } from "@/hooks/useReportFilters";

// Mock next/navigation so the hook can seed its initial state from the URL
// query params (the AC5.34.6 deep-link contract). Tests set `urlParams` and the
// mocked `useSearchParams().get()` reads from it.
let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (key: string) => urlParams.get(key) }),
}));

describe("useReportFilters", () => {
  beforeEach(() => {
    urlParams = new URLSearchParams();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // AC-reporting.fe-viz-reports.20
  it("AC5.34.3 builds query string from filter state", () => {
    const { result } = renderHook(() =>
      useReportFilters({
        reportType: "income-statement",
        initialStartDate: "2026-01-01",
        initialEndDate: "2026-06-30",
        initialCurrency: "USD",
      }),
    );

    const params = new URLSearchParams(result.current.queryString);
    expect(params.get("start_date")).toBe("2026-01-01");
    expect(params.get("end_date")).toBe("2026-06-30");
    expect(params.get("currency")).toBe("USD");
  });

  // AC-reporting.fe-viz-reports.21
  it("AC5.34.4 derives csv export path for report type", () => {
    const { result } = renderHook(() =>
      useReportFilters({
        reportType: "balance-sheet",
        initialAsOfDate: "2026-06-30",
        initialCurrency: "SGD",
      }),
    );

    expect(result.current.exportPath).toContain(
      "/api/reports/export?report_type=balance-sheet&format=csv&",
    );
    expect(result.current.exportPath).toContain("as_of_date=2026-06-30");
    expect(result.current.exportPath).toContain("currency=SGD");
  });

  // AC-reporting.fe-viz-reports.22
  it("AC5.34.5 updates query string when currency changes", () => {
    const { result } = renderHook(() =>
      useReportFilters({
        reportType: "cash-flow",
        initialStartDate: "2026-05-01",
        initialEndDate: "2026-06-01",
        initialCurrency: "SGD",
      }),
    );

    expect(new URLSearchParams(result.current.queryString).get("currency")).toBe("SGD");

    act(() => {
      result.current.setCurrency("EUR");
    });

    expect(new URLSearchParams(result.current.queryString).get("currency")).toBe("EUR");
  });

  // AC-reporting.fe-viz-reports.23
  it("AC5.34.6 seeds initial filter state from URL query params", () => {
    urlParams = new URLSearchParams({
      as_of_date: "2026-05-31",
      start_date: "2026-04-01",
      end_date: "2026-05-31",
      currency: "USD",
    });

    const { result } = renderHook(() =>
      useReportFilters({ reportType: "balance-sheet" }),
    );

    expect(result.current.asOfDate).toBe("2026-05-31");
    expect(result.current.startDate).toBe("2026-04-01");
    expect(result.current.endDate).toBe("2026-05-31");
    expect(result.current.currency).toBe("USD");

    const params = new URLSearchParams(result.current.queryString);
    expect(params.get("as_of_date")).toBe("2026-05-31");
    expect(params.get("currency")).toBe("USD");
  });

  it("AC5.34.6 lets an explicit option override the URL query param", () => {
    urlParams = new URLSearchParams({
      as_of_date: "2026-05-31",
      currency: "USD",
    });

    const { result } = renderHook(() =>
      useReportFilters({
        reportType: "balance-sheet",
        initialAsOfDate: "2026-01-15",
        initialCurrency: "SGD",
      }),
    );

    expect(result.current.asOfDate).toBe("2026-01-15");
    expect(result.current.currency).toBe("SGD");
  });

  it("AC5.34.6 falls back to defaults when neither option nor URL is present", () => {
    const { result } = renderHook(() =>
      useReportFilters({ reportType: "balance-sheet" }),
    );

    // No URL param and no option: as-of date defaults to today, currency to SGD.
    expect(result.current.asOfDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(result.current.currency).toBe("SGD");
  });
});
