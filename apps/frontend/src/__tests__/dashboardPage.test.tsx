import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomePage from "@/app/(main)/page"
import { apiOperation } from "@/lib/api-client"

import { setTestUrl } from "./helpers/nextNavigation"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a>,
}))

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const liquidBalance = {
  as_of_date: "2026-10-22",
  currency: "USD",
  assets: [{ account_id: "a1", name: "Cash", type: "ASSET", amount: "5000" }],
  liabilities: [{ account_id: "l1", name: "Card", type: "LIABILITY", amount: "1000" }],
  equity: [],
  total_assets: "5000",
  total_liabilities: "1000",
  total_equity: "4000",
  equation_delta: "0",
  is_balanced: true,
}

const income = {
  start_date: "2025-11-01",
  end_date: "2026-10-22",
  currency: "USD",
  income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "3500" }],
  expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "1200" }],
  total_income: "3500",
  total_expenses: "1200",
  net_income: "2300",
  trends: [],
}

const cashFlow = {
  start_date: "2025-11-01",
  end_date: "2026-10-22",
  currency: "USD",
  operating: [],
  investing: [],
  financing: [],
  summary: {
    operating_activities: "2300",
    investing_activities: "0",
    financing_activities: "-300",
    net_cash_flow: "2000",
    beginning_cash: "3000",
    ending_cash: "5000",
  },
}

const readyWorkflow = {
  primary_state: "ready",
  next_action: { type: "open_report", count: 1, href: "/reports?tab=package", label: "Open report package", summary: "Reports are ready." },
  report_readiness: { state: "ready", blocking_count: 0, href: "/reports?tab=package" },
  event_counts: { unread: 0, action_required: 0, blocked: 0 },
}

type Overrides = Partial<Record<string, () => Promise<unknown>>>

function mockHomeApi(overrides: Overrides = {}) {
  vi.mocked(apiOperation).mockImplementation(((operationId: string, request: { query?: Record<string, unknown> } = {}) => {
    if (overrides[operationId]) return overrides[operationId]!()
    switch (operationId) {
      case "balance_sheet_reports_balance_sheet_get":
        return Promise.resolve(
          request.query?.include_restricted
            ? { ...liquidBalance, total_assets: "17500", assets: [...liquidBalance.assets, { account_id: "r1", name: "SHOP RSU", type: "ASSET", amount: "12500" }] }
            : liquidBalance,
        )
      case "income_statement_reports_income_statement_get":
        return Promise.resolve(income)
      case "cash_flow_reports_cash_flow_get":
        return Promise.resolve(cashFlow)
      case "get_workflow_status_endpoint_workflow_status_get":
        return Promise.resolve(readyWorkflow)
      case "list_statements_statements_get":
        return Promise.resolve({ items: [{ id: "s1", status: "approved", original_filename: "dbs.pdf" }], total: 1 })
      case "reconciliation_stats_reconciliation_stats_get":
        return Promise.resolve({ total_transactions: 20, matched_transactions: 20, unmatched_transactions: 0, pending_review: 0, auto_accepted: 4, match_rate: 100, score_distribution: {} })
      case "list_processing_pending_accounts_processing_pending_get":
        return Promise.resolve({ items: [], total: 0 })
      case "suggestions_chat_suggestions_get":
        return Promise.resolve({ suggestions: [], structured_suggestions: [] })
      case "get_available_currencies_reports_currencies_get":
        return Promise.resolve(["SGD", "USD"])
      case "get_base_currency_app_config_base_currency_get":
        return Promise.resolve({ base_currency: "USD" })
      default:
        return Promise.reject(new Error(`unhandled operation ${operationId}`))
    }
  }) as never)
}

const workflow = (state: string, nextAction: Record<string, unknown>) => () =>
  Promise.resolve({ ...readyWorkflow, primary_state: state, next_action: { count: 1, summary: "", ...nextAction } })

describe("HomePage", () => {
  const mockedApiOperation = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiOperation.mockReset()
    mockHomeApi()
    setTestUrl("/")
  })

  // AC-reporting.fe-report-surfaces.1
  it("AC16.12.1 shows loading state before dashboard data resolves", () => {
    mockHomeApi({
      balance_sheet_reports_balance_sheet_get: () => new Promise(() => undefined),
      income_statement_reports_income_statement_get: () => new Promise(() => undefined),
      cash_flow_reports_cash_flow_get: () => new Promise(() => undefined),
    })
    render(<HomePage />)

    for (const card of ["balance-sheet", "income-statement", "cash-flow"]) {
      expect(within(screen.getByTestId(`cockpit-card-${card}`)).getByRole("status")).toHaveTextContent("Loading…")
    }
  })

  // AC-reporting.fe-report-surfaces.2
  it("AC16.12.2 renders error fallback and retry action on failure", async () => {
    let failures = 0
    mockHomeApi({
      income_statement_reports_income_statement_get: () => (failures++ === 0 ? Promise.reject(new Error("income down")) : Promise.resolve(income)),
    })
    render(<HomePage />)

    expect(await screen.findByText("Statements unavailable: income down")).toBeInTheDocument()
    // The other cards keep their own data.
    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.queryByText(/Statements unavailable/)).toBeNull())
    expect(within(screen.getByTestId("cockpit-card-income-statement")).getByText("Net income").nextElementSibling).toHaveTextContent("+$2,300")
  })

  // AC-reporting.fe-report-surfaces.3 / AC-reporting.fe-ia-reports.1 / AC-meta.fe-app-shell.4
  it("AC16.12.3 AC22.1.2 renders the dimension bar and the three statement cards of the period", async () => {
    render(<HomePage />)

    expect(screen.getByRole("heading", { name: "Home", level: 1 })).toBeInTheDocument()
    expect(screen.getByRole("group", { name: "Report dimensions" })).toBeInTheDocument()
    const balance = screen.getByTestId("cockpit-card-balance-sheet")
    await waitFor(() => expect(within(balance).getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    expect(within(balance).getByText("Total assets").nextElementSibling).toHaveTextContent("$5,000")
    const incomeCard = screen.getByTestId("cockpit-card-income-statement")
    await waitFor(() => expect(within(incomeCard).getByText("Savings rate").nextElementSibling).toHaveTextContent("66%"))
    const cash = screen.getByTestId("cockpit-card-cash-flow")
    await waitFor(() => expect(within(cash).getByText("Financing").nextElementSibling).toHaveTextContent("-$300"))
    expect(within(cash).getByText("Net change").nextElementSibling).toHaveTextContent("+$2,000")
  })

  // AC-reporting.fe-report-surfaces.4
  it("AC16.12.4 shows zero metrics and no line list for an empty period", async () => {
    mockHomeApi({
      balance_sheet_reports_balance_sheet_get: () =>
        Promise.resolve({ ...liquidBalance, assets: [], liabilities: [], total_assets: "0", total_liabilities: "0", total_equity: "0" }),
      income_statement_reports_income_statement_get: () =>
        Promise.resolve({ ...income, income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0" }),
    })
    render(<HomePage />)

    const balance = screen.getByTestId("cockpit-card-balance-sheet")
    await waitFor(() => expect(within(balance).getByText("Net worth").nextElementSibling).toHaveTextContent("$0"))
    expect(screen.queryByText(/Largest lines/)).toBeNull()
    // No income: no savings rate.
    const incomeCard = screen.getByTestId("cockpit-card-income-statement")
    await waitFor(() => expect(within(incomeCard).getByText("Savings rate").nextElementSibling).toHaveTextContent("—"))
  })

  // AC-reporting.fe-ia-reports.7
  it("AC22.4.4 keeps Home lean: one cockpit and no analytics panel or duplicate metric block", async () => {
    render(<HomePage />)

    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    expect(screen.queryByRole("button", { name: /Show analytics/i })).toBeNull()
    for (const label of ["Net worth", "Total assets", "Expenses", "Net income", "Savings rate", "Operating"]) {
      expect(screen.getAllByText(label)).toHaveLength(1)
    }
    for (const removed of ["Annualized Income", "Restricted Holdings", "Risk radar", "Recent Entries", "Unmatched Alerts"]) {
      expect(screen.queryByText(removed)).toBeNull()
    }
  })

  // AC-reporting.fe-remainder-reports.6 / AC-reporting.fe-remainder-reports.4
  it("AC19.4.3 shows one action banner that follows the workflow next action", async () => {
    mockHomeApi({
      get_workflow_status_endpoint_workflow_status_get: workflow("needs_action", { type: "review_required", href: "/audit", label: "Review required", summary: "Confirm the source." }),
    })
    const view = render(<HomePage />)

    const banner = await screen.findByRole("region", { name: "Needs attention" })
    expect(within(banner).getByRole("heading", { name: "An item needs your review" })).toBeInTheDocument()
    expect(banner).toHaveTextContent("Confirm the source.")
    expect(within(banner).getByRole("link", { name: "Review required" })).toHaveAttribute("href", "/audit")
    view.unmount()

    mockHomeApi({
      get_workflow_status_endpoint_workflow_status_get: workflow("blocked", { type: "resolve_blocker", href: "/journal", label: "Resolve blocker" }),
    })
    render(<HomePage />)
    const blocked = await screen.findByRole("region", { name: "Needs attention" })
    expect(within(blocked).getByRole("heading", { name: "A blocker holds your reports" })).toBeInTheDocument()
    // With no summary from the backend, the banner states the workflow state.
    expect(blocked).toHaveTextContent("A blocker is holding report readiness.")
    expect(within(blocked).getByRole("link", { name: "Resolve blocker" })).toHaveAttribute("href", "/journal")
    expect(screen.getAllByRole("region", { name: "Needs attention" })).toHaveLength(1)
  })

  // AC-reporting.fe-report-surfaces.5 / AC-reporting.fe-report-surfaces.6 / AC-reporting.fe-ia-reports.20
  it("AC22.16.1 AC16.12.17 AC16.12.18 asks a new user to upload the first statement", async () => {
    mockHomeApi({
      get_workflow_status_endpoint_workflow_status_get: workflow("empty", { type: "upload", count: 0, href: "/statements/upload" }),
      list_statements_statements_get: () => Promise.resolve({ items: [], total: 0 }),
    })
    render(<HomePage />)

    const banner = await screen.findByRole("region", { name: "Needs attention" })
    expect(within(banner).getByRole("heading", { name: "Upload your first statement" })).toBeInTheDocument()
    expect(within(banner).getByRole("link", { name: "Upload statements" })).toHaveAttribute("href", "/upload")
    for (const link of screen.getAllByRole("link")) {
      expect(["/accounts", "/settings?tab=accounts"]).not.toContain(link.getAttribute("href"))
    }
  })

  // AC-reporting.fe-report-surfaces.7
  it("AC16.12.19 hides the action banner when nothing needs attention", async () => {
    render(<HomePage />)

    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("list_processing_pending_accounts_processing_pending_get", expect.anything()),
    )
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull()
  })

  // AC-reporting.fe-ia-reports.9 / AC-reporting.fe-ia-reports.21
  it("AC22.16.2 AC22.5.6 routes the confirmation count to the one /audit queue", async () => {
    mockHomeApi({
      list_statements_statements_get: () =>
        Promise.resolve({
          items: [
            { id: "s1", status: "parsed", original_filename: "dbs.pdf", confidence_score: 60 },
            { id: "s2", status: "parsed", original_filename: "ocbc.pdf", confidence_score: 90 },
          ],
          total: 2,
        }),
    })
    render(<HomePage />)

    const banner = await screen.findByRole("region", { name: "Needs attention" })
    expect(within(banner).getByRole("heading", { name: "2 items need your confirmation" })).toBeInTheDocument()
    expect(within(banner).getByRole("link", { name: "Open Needs Confirmation" })).toHaveAttribute("href", "/audit")
  })

  // AC-reporting.fe-remainder-reports.5
  it("AC19.4.2 AC16.16.1 renders the action banner before the dimension bar and the statement cards", async () => {
    mockHomeApi({
      get_workflow_status_endpoint_workflow_status_get: workflow("needs_action", { type: "review_required", href: "/audit", label: "Review required" }),
    })
    render(<HomePage />)

    const banner = await screen.findByRole("region", { name: "Needs attention" })
    const bar = screen.getByRole("group", { name: "Report dimensions" })
    const cockpit = screen.getByRole("region", { name: "Three-statement cockpit" })
    expect(banner.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(bar.compareDocumentPosition(cockpit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  // AC-reporting.fe-remainder-reports.9
  it("AC19.4.6 keeps the statement cards visible when the workflow status fails", async () => {
    mockHomeApi({
      get_workflow_status_endpoint_workflow_status_get: () => Promise.reject(new Error("workflow down")),
    })
    render(<HomePage />)

    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull()
    expect(screen.queryByText(/workflow down/)).toBeNull()
  })

  // AC-portfolio.fe-assets2.9
  it("AC11.8.5 defaults to liquid net worth and refetches when restricted holdings are included", async () => {
    render(<HomePage />)

    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    expect(mockedApiOperation).toHaveBeenCalledWith(
      "balance_sheet_reports_balance_sheet_get",
      expect.objectContaining({ query: expect.objectContaining({ include_restricted: false }) }),
    )
    const scope = screen.getByLabelText("Include restricted holdings")
    expect(scope).not.toBeChecked()
    fireEvent.click(scope)

    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$16,500"))
    expect(mockedApiOperation).toHaveBeenCalledWith(
      "balance_sheet_reports_balance_sheet_get",
      expect.objectContaining({ query: expect.objectContaining({ include_restricted: true }) }),
    )
    expect(screen.getByLabelText("Include restricted holdings")).toBeChecked()
  })

  // AC-reporting.fe-viz-reports.27
  it("renders the advisor brief after the statement cards and keeps the cockpit when suggestions fail", async () => {
    mockHomeApi({
      suggestions_chat_suggestions_get: () =>
        Promise.resolve({
          suggestions: [],
          structured_suggestions: [
            { basis: "Report package is blocked by one review item.", confidence_tier: "blocked", source_refs: ["report_package.readiness"], limitation: "Review the blocker first.", next_action_href: "/audit" },
          ],
        }),
    })
    const view = render(<HomePage />)

    const brief = await screen.findByLabelText("Advisor Brief")
    expect(screen.getByRole("region", { name: "Three-statement cockpit" }).compareDocumentPosition(brief) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    view.unmount()

    mockHomeApi({ suggestions_chat_suggestions_get: () => Promise.reject(new Error("suggestions down")) })
    render(<HomePage />)
    await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"))
    expect(screen.queryByLabelText("Advisor Brief")).toBeNull()
  })
})
