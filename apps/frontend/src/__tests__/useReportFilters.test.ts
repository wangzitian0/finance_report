import { act, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  readReportFilters,
  reportsHref,
  resolvePeriodRange,
  useReportFilters,
  type ReportPeriodPreset,
} from "@/hooks/useReportFilters"

import { routerReplace, setTestUrl, testUrl } from "./helpers/nextNavigation"

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)
// The hook reads GET /reports/coverage. No cash opening position: no bound.
vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn(() => Promise.resolve({ as_of_date: "2026-10-22", coverage_start: null })) }))

const TODAY = new Date(2026, 9, 22)
const read = (query: string) => readReportFilters(new URLSearchParams(query), TODAY)

describe("report period dimensions", () => {
  // AC-reporting.fe-period-cockpit.1
  it("AC-reporting.fe-period-cockpit.1 resolves each preset to its first and last day", () => {
    const expected: Record<ReportPeriodPreset, string> = {
      "1M": "2026-10-01",
      "1Q": "2026-08-01",
      "1Y": "2025-11-01",
      YTD: "2026-01-01",
      "3Y": "2023-11-01",
      All: "2000-01-01",
    }
    for (const [preset, startDate] of Object.entries(expected)) {
      expect(resolvePeriodRange(preset as ReportPeriodPreset, TODAY)).toEqual({ startDate, endDate: "2026-10-22" })
    }
  })

  // AC-reporting.fe-period-cockpit.1
  it("AC-reporting.fe-period-cockpit.1 moves a period back and forward by one period length and stops at today", () => {
    const current = read("period=1M")
    expect(current).toMatchObject({ startDate: "2026-10-01", endDate: "2026-10-22", isCurrent: true, openingDate: "2026-09-30", nextEnd: null })

    const september = read(`period=1M&end=${current.openingDate}`)
    expect(september).toMatchObject({ startDate: "2026-09-01", endDate: "2026-09-30", isCurrent: false, openingDate: "2026-08-31", nextEnd: "" })
    expect(read("period=1M&end=2026-08-31")).toMatchObject({ startDate: "2026-08-01", nextEnd: "2026-09-30" })

    expect(read("period=1Q&end=2026-07-31")).toMatchObject({ startDate: "2026-05-01", endDate: "2026-07-31", nextEnd: "" })
    expect(read("period=1Q&end=2026-04-30")).toMatchObject({ startDate: "2026-02-01", nextEnd: "2026-07-31" })
    expect(read("end=2025-10-31")).toMatchObject({ preset: "1Y", startDate: "2024-11-01", nextEnd: "" })
    expect(read("period=YTD&end=2024-12-31")).toMatchObject({ startDate: "2024-01-01", openingDate: "2023-12-31", nextEnd: "2025-12-31" })
    expect(read("period=3Y&end=2023-10-31")).toMatchObject({ startDate: "2020-11-01", nextEnd: "" })
    expect(read("period=All&end=2025-01-31")).toMatchObject({ startDate: "2000-01-01", openingDate: null, nextEnd: null })
  })

  // AC-reporting.fe-period-cockpit.2 / AC-reporting.fe-viz-reports.20 / AC-reporting.fe-viz-reports.23
  it("AC-reporting.fe-period-cockpit.2 reads the dimensions from the URL and falls back to defaults on invalid values", () => {
    // The default scope includes restricted holdings (#2645). Only the liquid scope is written to the URL.
    expect(read("tab=cash-flow&period=YTD&end=2026-03-31&currency=USD&include_restricted=false")).toMatchObject({
      tab: "cash-flow",
      preset: "YTD",
      startDate: "2026-01-01",
      endDate: "2026-03-31",
      currency: "USD",
      includeRestricted: false,
      dimensionQuery: "period=YTD&end=2026-03-31&currency=USD&include_restricted=false",
    })
    // An old link that names the default scope still reads it, and the canonical query omits it.
    expect(read("include_restricted=true")).toMatchObject({ includeRestricted: true, dimensionQuery: "" })
    expect(read("tab=ledger&period=2W&end=2026-13-01&currency=usd&include_restricted=yes")).toMatchObject({
      tab: "overview",
      preset: "1Y",
      endDate: "2026-10-22",
      isCurrent: true,
      currency: undefined,
      includeRestricted: true,
      dimensionQuery: "",
    })
    expect(read("end=2026-02-30").isCurrent).toBe(true)
    // A future end keeps its date and has no next period.
    expect(read("period=1Y&end=2026-12-31")).toMatchObject({ startDate: "2026-01-01", endDate: "2026-12-31", isCurrent: false, nextEnd: null })
    // A custom period: a start and an end, no preset and no step. A start after the end is ignored.
    expect(read("period=1M&start=2025-02-15&end=2025-03-14")).toMatchObject({
      preset: null,
      startDate: "2025-02-15",
      endDate: "2025-03-14",
      openingDate: "2025-02-14",
      previousEnd: null,
      nextEnd: null,
      dimensionQuery: "start=2025-02-15&end=2025-03-14",
    })
    expect(read("start=2026-09-01")).toMatchObject({ preset: null, startDate: "2026-09-01", endDate: "2026-10-22", isCurrent: true })
    expect(read("start=2025-04-01&end=2025-03-31")).toMatchObject({ preset: "1Y", startDate: "2024-04-01", endDate: "2025-03-31" })
    // The redirects of the old report routes keep their query: `as_of_date` and `end_date` still set the period end.
    expect(read("as_of_date=2025-12-31").endDate).toBe("2025-12-31")
    expect(read("start_date=2025-01-01&end_date=2025-06-30")).toMatchObject({ preset: null, startDate: "2025-01-01", endDate: "2025-06-30" })
  })

  // AC-reporting.fe-period-cockpit.7
  it("AC-reporting.fe-period-cockpit.7 starts a preset period no earlier than the coverage start", () => {
    const first = "2026-07-01"
    const bounded = (query: string) => readReportFilters(new URLSearchParams(query), TODAY, first)

    // The default 1Y period starts on 2025-11-01: the first statement moves its start, and its
    // opening balance sheet is the first statement day. No previous period exists.
    expect(bounded("")).toMatchObject({
      preset: "1Y",
      startDate: first,
      endDate: "2026-10-22",
      openingDate: first,
      opensAtCoverageStart: true,
      previousEnd: null,
      nextEnd: null,
      dimensionQuery: "",
    })
    expect(bounded("period=All")).toMatchObject({ startDate: first, openingDate: first, opensAtCoverageStart: true, previousEnd: null })
    expect(bounded("period=3Y")).toMatchObject({ startDate: first, openingDate: first })
    // A period that starts on the first statement day keeps its start and has no previous period.
    expect(bounded("period=1Q&end=2026-09-30")).toMatchObject({ startDate: first, openingDate: first, previousEnd: null, nextEnd: "" })
    // A bounded past period keeps its next period.
    expect(bounded("period=1Q&end=2026-07-31")).toMatchObject({ startDate: first, openingDate: first, previousEnd: null, nextEnd: "" })
    expect(bounded("period=1M&end=2026-07-31")).toMatchObject({ startDate: first, nextEnd: "2026-08-31" })
    // A period that starts after the first statement does not change.
    expect(bounded("period=1M")).toMatchObject({ startDate: "2026-10-01", openingDate: "2026-09-30", opensAtCoverageStart: false, previousEnd: "2026-09-30" })
    // A period that ends before the first statement does not change.
    expect(bounded("period=1M&end=2026-05-31")).toMatchObject({ startDate: "2026-05-01", openingDate: "2026-04-30", opensAtCoverageStart: false })
    // A custom period keeps its start. Its opening balance sheet is the first statement day.
    expect(bounded("start=2026-01-01&end=2026-09-30")).toMatchObject({
      preset: null,
      startDate: "2026-01-01",
      openingDate: first,
      opensAtCoverageStart: true,
      dimensionQuery: "start=2026-01-01&end=2026-09-30",
    })
    // No coverage start: no bound. An invalid date applies no bound either.
    expect(readReportFilters(new URLSearchParams(""), TODAY, null)).toMatchObject({ startDate: "2025-11-01", openingDate: "2025-10-31", opensAtCoverageStart: false })
    expect(readReportFilters(new URLSearchParams(""), TODAY, "2026-02-30")).toMatchObject({ startDate: "2025-11-01", opensAtCoverageStart: false })
  })

  // AC-reporting.fe-period-cockpit.2 / AC-reporting.fe-viz-reports.21
  it("AC-reporting.fe-period-cockpit.2 builds tab links that keep the dimension query", () => {
    expect(reportsHref("overview")).toBe("/reports")
    expect(reportsHref("overview", "period=1M")).toBe("/reports?period=1M")
    expect(reportsHref("cash-flow", "period=1M&currency=USD")).toBe("/reports?period=1M&currency=USD&tab=cash-flow")
  })
})

describe("useReportFilters", () => {
  beforeEach(() => {
    routerReplace.mockClear()
    setTestUrl("/reports?from=audit&tab=income-statement&end_date=2025-06-30")
  })

  // AC-reporting.fe-period-cockpit.2 / AC-reporting.fe-viz-reports.23
  it("AC-reporting.fe-period-cockpit.2 keeps the period of an old route link when another dimension changes", () => {
    setTestUrl("/reports?tab=balance-sheet&as_of_date=2025-12-31&currency=SGD")
    const { result } = renderHook(() => useReportFilters())

    act(() => result.current.setIncludeRestricted(false))
    expect(testUrl()).toBe("/reports?tab=balance-sheet&end=2025-12-31&currency=SGD&include_restricted=false")
    expect(result.current.endDate).toBe("2025-12-31")

    act(() => setTestUrl("/reports?tab=income-statement&start_date=2025-01-01&end_date=2025-06-30"))
    act(() => result.current.setCurrency("USD"))
    expect(testUrl()).toBe("/reports?tab=income-statement&start=2025-01-01&end=2025-06-30&currency=USD")
    expect(result.current).toMatchObject({ preset: null, startDate: "2025-01-01", endDate: "2025-06-30" })
  })

  // AC-reporting.fe-period-cockpit.2 / AC-reporting.fe-viz-reports.22
  it("AC-reporting.fe-period-cockpit.2 writes each dimension change to the URL and omits default values", () => {
    // Other parameters, such as `from`, stay after the dimensions.
    const { result } = renderHook(() => useReportFilters())
    expect(result.current.tab).toBe("income-statement")
    expect(result.current.endDate).toBe("2025-06-30")

    act(() => result.current.setPreset("1M"))
    expect(testUrl()).toBe("/reports?tab=income-statement&period=1M&from=audit")
    expect(result.current.isCurrent).toBe(true)

    act(() => result.current.goToPeriodEnd(result.current.openingDate!))
    expect(result.current.isCurrent).toBe(false)
    expect(testUrl()).toMatch(/&end=\d{4}-\d{2}-\d{2}&from=audit$/)
    // A preset starts at the current period: it clears the period end.
    act(() => result.current.setPreset("1Q"))
    expect(testUrl()).toBe("/reports?tab=income-statement&period=1Q&from=audit")
    act(() => result.current.setPreset("1M"))
    act(() => result.current.goToPeriodEnd(result.current.openingDate!))

    act(() => result.current.goToPeriodEnd(""))
    act(() => result.current.setCurrency("USD"))
    act(() => result.current.setIncludeRestricted(false))
    expect(testUrl()).toBe("/reports?tab=income-statement&period=1M&currency=USD&include_restricted=false&from=audit")

    act(() => result.current.setIncludeRestricted(true))
    act(() => result.current.setPreset("1Y"))
    expect(testUrl()).toBe("/reports?tab=income-statement&currency=USD&from=audit")
    expect(routerReplace).toHaveBeenLastCalledWith("/reports?tab=income-statement&currency=USD&from=audit", { scroll: false })
  })
})
