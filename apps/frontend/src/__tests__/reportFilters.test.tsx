import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { coverageNote, ReportDimensionBar } from "@/components/reports/ReportFilters"
import { useReportFilters } from "@/hooks/useReportFilters"
import { apiOperation } from "@/lib/api-client"

import { setTestUrl, testUrl } from "./helpers/nextNavigation"

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

function Bar({ showScope = false }: { showScope?: boolean }) {
  const filters = useReportFilters()
  return <ReportDimensionBar filters={filters} showScope={showScope} />
}

describe("ReportDimensionBar", () => {
  beforeEach(() => {
    vi.mocked(apiOperation).mockReset()
    vi.mocked(apiOperation).mockImplementation(((operationId: string) => {
      if (operationId === "get_available_currencies_reports_currencies_get") return Promise.resolve(["SGD", "USD", "EUR"])
      if (operationId === "get_base_currency_app_config_base_currency_get") return Promise.resolve({ base_currency: "EUR" })
      // No cash opening position: no coverage start bounds the period.
      if (operationId === "report_coverage_reports_coverage_get") return Promise.resolve({ as_of_date: "2026-01-31", coverage_start: null })
      return Promise.reject(new Error(`unexpected ${operationId}`))
    }) as never)
    setTestUrl("/reports?tab=cash-flow&period=1M&end=2026-01-31")
  })

  // AC-reporting.fe-viz-reports.18
  // AC-reporting.fe-period-cockpit.2
  it("AC-reporting.fe-period-cockpit.2 sets the preset and steps the period through the URL", async () => {
    render(<Bar />)

    expect(screen.getByRole("group", { name: "Reporting period" })).toBeInTheDocument()
    for (const preset of ["1M", "1Q", "1Y", "YTD", "3Y", "All"]) {
      expect(screen.getByRole("button", { name: `Period ${preset}` })).toHaveAttribute("aria-pressed", String(preset === "1M"))
    }
    // An explicit preset applies no coverage bound: its range shows at once (#2646).
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jan 1, 2026 – Jan 31, 2026")
    await waitFor(() => expect(vi.mocked(apiOperation).mock.calls.map(([id]) => id)).toContain("get_available_currencies_reports_currencies_get"))
    expect(vi.mocked(apiOperation).mock.calls.map(([id]) => id)).not.toContain("report_coverage_reports_coverage_get")

    fireEvent.click(screen.getByRole("button", { name: "Previous period" }))
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2025-12-31")
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Dec 1, 2025 – Dec 31, 2025")

    fireEvent.click(screen.getByRole("button", { name: "Next period" }))
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2026-01-31")

    fireEvent.click(screen.getByRole("button", { name: "Period YTD" }))
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=YTD")
    expect(screen.getByRole("button", { name: "Period YTD" })).toHaveAttribute("aria-pressed", "true")
    // The current period has no next period.
    expect(screen.getByRole("button", { name: "Next period" })).toBeDisabled()

    fireEvent.click(screen.getByRole("button", { name: "Period All" }))
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled()
    expect(screen.queryByLabelText("Include restricted holdings")).toBeNull()
  })

  // AC-reporting.fe-period-cockpit.7
  it("AC-reporting.fe-period-cockpit.7 bounds the default view, names the limiting accounts, and shows an explicit 1Y in full", async () => {
    vi.mocked(apiOperation).mockImplementation(((operationId: string, request?: { query?: { as_of_date?: string } }) => {
      if (operationId === "report_coverage_reports_coverage_get") {
        return Promise.resolve({
          as_of_date: request?.query?.as_of_date,
          coverage_start: "2026-01-15",
          limiting_accounts: ["DBS Savings", "OCBC Bank"],
        })
      }
      if (operationId === "get_available_currencies_reports_currencies_get") return Promise.resolve(["SGD"])
      if (operationId === "get_base_currency_app_config_base_currency_get") return Promise.resolve({ base_currency: "SGD" })
      return Promise.reject(new Error(`unexpected ${operationId}`))
    }) as never)
    setTestUrl("/reports?end=2026-01-31")
    render(<Bar />)

    // The default view waits for the coverage start, then starts on it.
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("…")
    await waitFor(() => expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jan 15, 2026 – Jan 31, 2026"))
    expect(screen.getByTestId("report-coverage-note")).toHaveTextContent(
      "Starts Jan 15, 2026: DBS Savings and OCBC Bank have no opening balance before this date. Add an opening balance",
    )
    expect(screen.getByRole("link", { name: "Add an opening balance" })).toHaveAttribute("href", "/settings?tab=accounts")
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled()

    // The 1Y button makes the preset explicit: the full period, no note, and a previous period.
    fireEvent.click(screen.getByRole("button", { name: "Period 1Y" }))
    expect(testUrl()).toBe("/reports?period=1Y")
    act(() => setTestUrl("/reports?period=1Y&end=2026-01-31"))
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Feb 1, 2025 – Jan 31, 2026")
    expect(screen.queryByTestId("report-coverage-note")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Previous period" }))
    expect(testUrl()).toBe("/reports?period=1Y&end=2025-01-31")
  })

  // AC-reporting.fe-period-cockpit.7
  it("AC-reporting.fe-period-cockpit.7 disables Previous and Custom while the default view waits for the coverage start", async () => {
    let release: (value: unknown) => void = () => undefined
    const coverage = new Promise((resolve) => {
      release = resolve
    })
    vi.mocked(apiOperation).mockImplementation(((operationId: string) => {
      if (operationId === "report_coverage_reports_coverage_get") return coverage
      if (operationId === "get_available_currencies_reports_currencies_get") return Promise.resolve(["SGD"])
      if (operationId === "get_base_currency_app_config_base_currency_get") return Promise.resolve({ base_currency: "SGD" })
      return Promise.reject(new Error(`unexpected ${operationId}`))
    }) as never)
    setTestUrl("/reports?end=2026-01-31")
    render(<Bar />)

    // The shown range is not known yet: neither control may act on the unbounded range.
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("…")
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Custom period" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "Previous period" }))
    fireEvent.click(screen.getByRole("button", { name: "Custom period" }))
    expect(testUrl()).toBe("/reports?end=2026-01-31")

    // No coverage start: no bound, and both controls work.
    await act(async () => {
      release({ as_of_date: "2026-01-31", coverage_start: null, limiting_accounts: [] })
      await coverage
    })
    await waitFor(() => expect(screen.getByTestId("report-period-range")).toHaveTextContent("Feb 1, 2025 – Jan 31, 2026"))
    expect(screen.getByRole("button", { name: "Previous period" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Custom period" })).toBeEnabled()
  })

  // AC-reporting.fe-period-cockpit.7
  it("AC-reporting.fe-period-cockpit.7 names one, several or no limiting accounts in the coverage note", () => {
    expect(coverageNote("2026-10-01", ["OCBC Bank"])).toBe("Starts Oct 1, 2026: OCBC Bank has no opening balance before this date.")
    expect(coverageNote("2026-10-01", ["A", "B", "C"])).toBe("Starts Oct 1, 2026: A, B and C have no opening balance before this date.")
    expect(coverageNote("2026-10-01", [])).toBe("Starts Oct 1, 2026: Your cash accounts have no opening balance before this date.")
  })

  // AC-reporting.fe-period-cockpit.2
  it("AC-reporting.fe-period-cockpit.2 sets a custom period through the URL and keeps its start on or before its end", () => {
    render(<Bar />)

    fireEvent.click(screen.getByRole("button", { name: "Custom period" }))
    expect(testUrl()).toBe("/reports?tab=cash-flow&start=2026-01-01&end=2026-01-31")
    expect(screen.getByRole("button", { name: "Custom period" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("button", { name: "Period 1M" })).toHaveAttribute("aria-pressed", "false")
    // A custom period has no previous or next step.
    expect(screen.queryByRole("button", { name: "Previous period" })).toBeNull()

    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2025-12-15" } })
    expect(testUrl()).toBe("/reports?tab=cash-flow&start=2025-12-15&end=2026-01-31")
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2025-12-01" } })
    expect(testUrl()).toBe("/reports?tab=cash-flow&start=2025-12-01&end=2025-12-01")
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2025-12-20" } })
    expect(testUrl()).toBe("/reports?tab=cash-flow&start=2025-12-20&end=2025-12-20")
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "" } })
    expect(testUrl()).toBe("/reports?tab=cash-flow&start=2025-12-20&end=2025-12-20")

    fireEvent.click(screen.getByRole("button", { name: "Period 1Q" }))
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=1Q")
    expect(screen.queryByLabelText("Period start")).toBeNull()
  })

  // AC-reporting.fe-viz-reports.19
  it("AC5.34.2 shows the base currency until the URL names one and writes the selected currency to the URL", async () => {
    render(<Bar showScope />)

    const select = screen.getByRole("combobox", { name: "Reporting currency" })
    expect(await screen.findByRole("option", { name: "USD" })).toBeInTheDocument()
    expect(await screen.findByDisplayValue("EUR")).toBe(select)

    fireEvent.change(select, { target: { value: "USD" } })
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2026-01-31&currency=USD")
    expect(select).toHaveValue("USD")

    // The default scope includes restricted holdings (#2645). Unchecking writes the liquid scope.
    expect(screen.getByLabelText("Include restricted holdings")).toBeChecked()
    fireEvent.click(screen.getByLabelText("Include restricted holdings"))
    expect(testUrl()).toContain("include_restricted=false")
    expect(screen.getByLabelText("Include restricted holdings")).not.toBeChecked()
  })

  it("keeps a URL currency that the currency list does not name", () => {
    setTestUrl("/reports?currency=JPY")
    render(<Bar />)

    expect(screen.getByRole("combobox", { name: "Reporting currency" })).toHaveValue("JPY")
  })
})
