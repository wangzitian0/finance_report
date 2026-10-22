import { render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"
import { apiOperation } from "@/lib/api-client"

import { setTestUrl } from "./helpers/nextNavigation"
import { normalizablePackageDocument } from "./helpers/packageDocumentFixture"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}))

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }),
}))

vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const mockedApiOperation = vi.mocked(apiOperation)

const readiness = {
  package_id: "personal-financial-report-package",
  state: "blocked",
  label: "Blocked",
  action_href: "/journal",
  blocking_count: 2,
  blockers: [
    {
      code: "pending_review",
      label: "Pending source review",
      severity: "blocking",
      count: 1,
      reason: "Statement review must be completed before reports are trusted.",
      action_href: "/audit",
    },
    {
      code: "missing_source_coverage",
      label: "Missing source coverage",
      severity: "blocking",
      count: 1,
      reason: "Manual records need explicit source anchors.",
      action_href: "/journal",
    },
  ],
  input_coverage: {
    manifest_decision_count: 4,
    authoritative_input_count: 4,
    unproven_input_count: 2,
  },
}

const readyReadiness = {
  ...readiness,
  state: "ready",
  label: "Ready",
  action_href: "/journal",
  blocking_count: 0,
  blockers: [],
  input_coverage: { manifest_decision_count: 1, authoritative_input_count: 1, unproven_input_count: 0 },
}

const balanceSheet = {
  as_of_date: "2026-10-22",
  currency: "SGD",
  assets: [{ account_id: "a1", name: "DBS Savings", type: "ASSET", amount: "12000.00" }],
  liabilities: [{ account_id: "l1", name: "Credit Card", type: "LIABILITY", amount: "2000.00" }],
  equity: [],
  total_assets: "12000.00",
  total_liabilities: "2000.00",
  total_equity: "10000.00",
  equation_delta: "0.00",
  is_balanced: true,
}

const incomeStatement = {
  start_date: "2025-11-01",
  end_date: "2026-10-22",
  currency: "SGD",
  income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "60000.00" }],
  expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "24000.00" }],
  total_income: "60000.00",
  total_expenses: "24000.00",
  net_income: "36000.00",
  trends: [],
}

const cashFlow = {
  start_date: "2025-11-01",
  end_date: "2026-10-22",
  currency: "SGD",
  operating: [],
  investing: [],
  financing: [],
  summary: {
    operating_activities: "36000.00",
    investing_activities: "-5000.00",
    financing_activities: "0.00",
    net_cash_flow: "31000.00",
    beginning_cash: "0.00",
    ending_cash: "31000.00",
  },
}

function mockReports(packageAnswer: () => Promise<unknown> = () => Promise.resolve(normalizablePackageDocument({ readiness }))) {
  mockedApiOperation.mockImplementation(((operationId: string) => {
    if (operationId === "preview_personal_report_package_reports_package_get") return packageAnswer()
    if (operationId === "balance_sheet_reports_balance_sheet_get") return Promise.resolve(balanceSheet)
    if (operationId === "income_statement_reports_income_statement_get") return Promise.resolve(incomeStatement)
    if (operationId === "cash_flow_reports_cash_flow_get") return Promise.resolve(cashFlow)
    return Promise.resolve({})
  }) as never)
}

beforeEach(() => {
  mockedApiOperation.mockReset()
  mockReports()
  setTestUrl("/reports")
})

describe("Reports page (#2621 LC)", () => {
  // AC-reporting.fe-period-cockpit.3
  // AC-reporting.fe-report-surfaces.8 / AC-reporting.fe-ia-reports.3
  it("AC-reporting.fe-period-cockpit.3 renders the five report tabs, selects the tab of the URL, and keeps the dimensions in each tab link", async () => {
    setTestUrl("/reports?tab=income-statement&period=1M&end=2026-03-31&currency=USD")
    render(<ReportsPage />)

    const tablist = screen.getByRole("tablist", { name: "Report tabs" })
    const tabs = within(tablist).getAllByRole("tab")
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Overview", "Balance sheet", "Income statement", "Cash flow", "Full package"])
    expect(within(tablist).getByRole("tab", { name: "Income statement" })).toHaveAttribute("aria-selected", "true")
    expect(within(tablist).getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false")
    expect(within(tablist).getByRole("tab", { name: "Overview" })).toHaveAttribute("href", "/reports?period=1M&end=2026-03-31&currency=USD")
    expect(within(tablist).getByRole("tab", { name: "Cash flow" })).toHaveAttribute(
      "href",
      "/reports?period=1M&end=2026-03-31&currency=USD&tab=cash-flow",
    )
    expect(within(tablist).getByRole("tab", { name: "Full package" })).toHaveAttribute(
      "href",
      "/reports?period=1M&end=2026-03-31&currency=USD&tab=package",
    )
    expect(await screen.findByRole("heading", { name: "Income Statement" })).toBeInTheDocument()
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith(
        "income_statement_reports_income_statement_get",
        expect.objectContaining({ query: expect.objectContaining({ start_date: "2026-03-01", end_date: "2026-03-31", currency: "USD" }) }),
      ),
    )
    // The restricted-holdings scope shows only where a balance sheet shows.
    expect(screen.queryByLabelText("Include restricted holdings")).toBeNull()
  })

  // AC-reporting.fe-report-surfaces.9
  it("AC16.12.12 states the accounting equation on the Balance sheet tab", async () => {
    setTestUrl("/reports?tab=balance-sheet")
    render(<ReportsPage />)

    expect(await screen.findByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument()
    expect(screen.getByText("Assets = Liabilities + Equity")).toBeInTheDocument()
    expect(screen.getByText("✓ Balanced")).toBeInTheDocument()
    expect(screen.getByLabelText("Include restricted holdings")).not.toBeChecked()
  })

  // AC-reporting.fe-ia-reports.2
  it("AC22.3.1 leads with the three statement cards and their live figures for the period", async () => {
    render(<ReportsPage />)

    const balance = await screen.findByTestId("cockpit-card-balance-sheet")
    await waitFor(() => expect(balance).toHaveTextContent("Net worth"))
    expect(balance).toHaveTextContent("SGD 10,000")
    const income = screen.getByTestId("cockpit-card-income-statement")
    expect(income).toHaveTextContent("Savings rate")
    expect(income).toHaveTextContent("60%")
    const cash = screen.getByTestId("cockpit-card-cash-flow")
    expect(cash).toHaveTextContent("Investing")
    expect(cash).toHaveTextContent("-SGD 5,000")
    expect(within(balance).getByRole("link", { name: "Open the balance sheet report" })).toHaveAttribute("href", "/reports?tab=balance-sheet")
  })

  // AC-reporting.fe-ia-reports.18
  it("AC22.9.1 keeps every Overview link inside the everyday surfaces, not the Advanced reconciliation surface", async () => {
    render(<ReportsPage />)

    await screen.findByRole("region", { name: "Report readiness cockpit" })
    await waitFor(() => expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveTextContent("Net worth"))
    expect(screen.queryByText("Reconciliation coverage")).toBeNull()
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).not.toMatch(/^\/reconciliation/)
    }
  })

  // AC-reporting.fe-viz-reports.32
  it("AC5.37.1 renders trust-first readiness before report cards", async () => {
    render(<ReportsPage />)

    const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
    await waitFor(() => expect(cockpit).toHaveTextContent("Blocked"))
    expect(cockpit).toHaveTextContent("2 blockers")
    expect(cockpit).toHaveTextContent("2 unproven inputs")
    expect(cockpit).toHaveTextContent("Pending source review")
    expect(screen.getByRole("link", { name: "Resolve report blockers" })).toHaveAttribute("href", "/journal")

    const overview = screen.getByRole("tabpanel")
    const order = overview.compareDocumentPosition(screen.getByTestId("cockpit-card-balance-sheet"))
    expect(order & Node.DOCUMENT_POSITION_CONTAINED_BY).toBeTruthy()
    expect(cockpit.compareDocumentPosition(screen.getByTestId("cockpit-card-balance-sheet")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  // AC-reporting.fe-viz-reports.33
  it("AC5.37.2 preserves report navigation when readiness is unavailable", async () => {
    mockReports(() => Promise.reject(new Error("readiness down")))
    render(<ReportsPage />)

    expect(await screen.findByText("Readiness unavailable")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open report package" })).toHaveAttribute("href", "/reports?tab=package")
    expect(screen.getByRole("tab", { name: "Balance sheet" })).toBeInTheDocument()
    expect(screen.getByTestId("cockpit-card-income-statement")).toBeInTheDocument()
  })

  it("AC5.37.2 shows a checking state while readiness is still loading", () => {
    mockReports(() => new Promise(() => undefined))
    render(<ReportsPage />)

    expect(screen.getByRole("region", { name: "Report readiness cockpit" })).toHaveTextContent("Checking report readiness")
    expect(screen.getByRole("tab", { name: "Balance sheet" })).toBeInTheDocument()
  })

  it("AC5.37.1 renders non-blocked readiness states without blocker copy", async () => {
    for (const [state, label, badgeClass] of [
      ["ready", "Ready", "badge-success"],
      ["generated", "Generated", "badge-success"],
      ["processing", "Processing", "badge-warning"],
      ["stale", "Stale", "badge-error"],
      ["draft", "Draft", "badge-muted"],
    ] as const) {
      mockReports(() => Promise.resolve(normalizablePackageDocument({ readiness: { ...readyReadiness, state, label } })))

      const view = render(<ReportsPage />)
      const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
      await waitFor(() => expect(cockpit).toHaveTextContent(`Current package state is ${label.toLowerCase()}.`))
      const statusBadge = Array.from(cockpit.querySelectorAll(".badge")).find((badge) => badge.textContent === label)
      expect(statusBadge).toHaveClass(badgeClass)
      expect(screen.getByRole("link", { name: "Open readiness path" })).toHaveAttribute("href", "/journal")
      view.unmount()
    }
  })

  it("AC5.37.1 renders an all-clear source gap state when readiness has no gaps", async () => {
    mockReports(() => Promise.resolve(normalizablePackageDocument({ readiness: readyReadiness })))
    render(<ReportsPage />)

    const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
    await waitFor(() => expect(cockpit).toHaveTextContent("0 unproven inputs"))
    expect(cockpit).toHaveTextContent("All inputs in this package document have current authority decisions.")
    expect(cockpit).toHaveTextContent("No blockers reported.")
  })

  it("shows unavailable states, and keeps the tabs, when every live figure fails", async () => {
    mockedApiOperation.mockReset()
    mockedApiOperation.mockRejectedValue(new Error("offline"))
    render(<ReportsPage />)

    expect(await screen.findByText("Readiness unavailable")).toBeInTheDocument()
    expect(await screen.findByText("Statements unavailable: offline")).toBeInTheDocument()
    expect(screen.getAllByText("No data for this period.")).toHaveLength(3)
    expect(screen.getByRole("tablist", { name: "Report tabs" })).toBeInTheDocument()
  })
})
