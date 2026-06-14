import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useReportFilters } from "@/hooks/useReportFilters";

describe("useReportFilters", () => {
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
});
