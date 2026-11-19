import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readReportFilters, reportsHref, resolvePeriodRange, useReportFilters, type ReportPeriodPreset } from "@/hooks/useReportFilters";
import { apiOperation } from "@/lib/api";
import { routerReplace, setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(() => Promise.resolve({ as_of_date: "2026-10-22", coverage_start: null })) }));
const read = (q: string) => readReportFilters(new URLSearchParams(q), F.RF_TODAY);

describe("report period dimensions", () => {
  it("AC-reporting.fe-period-cockpit.1 resolves presets and steps period lengths", () => {
    for (const [p, startDate] of Object.entries(F.RF_PRESETS)) expect(resolvePeriodRange(p as ReportPeriodPreset, F.RF_TODAY)).toEqual({ startDate, endDate: "2026-10-22" });
    for (const [q, expected] of F.RF_STEP_CASES) expect(read(q)).toMatchObject(expected);
  });

  it("AC-reporting.fe-period-cockpit.2 parses URL dimensions, falls back on invalid input, and builds hrefs", () => {
    for (const [q, expected] of F.RF_URL_CASES) expect(read(q)).toMatchObject(expected);
    for (const [tab, qs, out] of [["overview", undefined, "/reports"], ["overview", "period=1M", "/reports?period=1M"], ["cash-flow", "period=1M&currency=USD", "/reports?period=1M&currency=USD&tab=cash-flow"]] as const) expect(reportsHref(tab, qs)).toBe(out);
  });

  it("AC-reporting.fe-period-cockpit.7 bounds default and All views by coverage start", () => {
    const b = (q: string) => readReportFilters(new URLSearchParams(q), F.RF_TODAY, F.RF_COV);
    for (const [q, expected] of F.RF_COV_CASES) expect(b(q)).toMatchObject(expected);
    F.assertFilterBounds(readReportFilters, F.RF_PRESETS);
  });
});

describe("useReportFilters", () => {
  beforeEach(() => { routerReplace.mockClear(); setTestUrl("/reports?from=audit&tab=income-statement&end_date=2025-06-30"); });

  it("AC-reporting.fe-period-cockpit.2 preserves old route dates and writes clean URL updates", () => F.assertHookUrlUpdates(useReportFilters));

  it("AC-reporting.fe-period-cockpit.7 requests coverage only for default view", async () => {
    const api = vi.mocked(apiOperation); api.mockClear(); setTestUrl("/reports?end=2026-09-30");
    const def = renderHook(() => useReportFilters()); expect(def.result.current.ready).toBe(false);
    await waitFor(() => expect(def.result.current.ready).toBe(true));
    expect(api.mock.calls).toEqual([["report_coverage_reports_coverage_get", { query: { as_of_date: "2026-09-30" } }]]); def.unmount();
    api.mockClear(); setTestUrl("/reports?period=1Y&end=2026-09-30");
    const exp = renderHook(() => useReportFilters());
    expect(exp.result.current).toMatchObject({ ready: true, isDefaultPeriod: false, startDate: "2025-10-01" });
    expect(api).not.toHaveBeenCalled();
  });
}); // AC-reporting.fe-viz-reports.20 AC-reporting.fe-viz-reports.21 AC-reporting.fe-viz-reports.22 AC-reporting.fe-viz-reports.23
