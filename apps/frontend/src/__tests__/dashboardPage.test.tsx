import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import DashboardPage from "@/app/(main)/dashboard/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a>,
}))

vi.mock("@/components/charts/BarChart", () => ({
  BarChart: () => <div>BarChartMock</div>,
}))

vi.mock("@/components/charts/PieChart", () => ({
  PieChart: () => <div>PieChartMock</div>,
}))

vi.mock("@/components/charts/TrendChart", () => ({
  TrendChart: () => <div>TrendChartMock</div>,
}))

vi.mock("@/components/charts/NetWorthTimeSeriesChart", () => ({
  NetWorthTimeSeriesChart: () => <div>NetWorthTimeSeriesMock</div>,
}))

vi.mock("@/lib/api", () => {
  const apiFetch = vi.fn()
  return {
    apiFetch,
    fetchWorkflowStatus: () => apiFetch("/api/workflow/status"),
    fetchWorkflowEvents: ({ limit }: { limit?: number } = {}) =>
      apiFetch(`/api/workflow/events${limit ? `?limit=${limit}` : ""}`),
    updateWorkflowEventStatus: (eventId: string, status: string) =>
      apiFetch(`/api/workflow/events/${eventId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
  }
})

const baseBalance = {
  assets: [{ account_id: "a1", name: "Cash", amount: 5000 }],
  liabilities: [],
  equity: [],
  total_assets: 5000,
  total_liabilities: 1000,
  total_equity: 4000,
  equation_delta: 0,
  currency: "USD",
  as_of_date: "2026-02-01",
  is_balanced: true,
}

const baseIncome = {
  currency: "USD",
  trends: [{ period_start: "2026-01-01", total_income: 3500, total_expenses: 1200, net_income: 2300 }],
}

function mockDashboardApi(overrides: Record<string, unknown> = {}) {
  const mockedApiFetch = vi.mocked(apiFetch)
  const hasOverride = (key: string) => Object.prototype.hasOwnProperty.call(overrides, key)
  let trendCalls = 0
  mockedApiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/reports/balance-sheet")) {
      if (overrides.balanceError) return Promise.reject(overrides.balanceError)
      const includeRestricted = path.includes("include_restricted=true")
      const defaultBalance = includeRestricted
        ? { ...baseBalance, total_assets: 17500, total_equity: 16500 }
        : baseBalance
      return Promise.resolve(hasOverride("balance") ? overrides.balance : defaultBalance)
    }
    if (path.startsWith("/api/workflow/status")) {
      return Promise.resolve(
        hasOverride("workflowStatus")
          ? overrides.workflowStatus
          : {
              primary_state: "needs_action",
              next_action: { type: "review_required", count: 1, href: "/review" },
              report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
              event_counts: { unread: 2, action_required: 1, blocked: 0 },
            },
      )
    }
    if (path.startsWith("/api/workflow/events")) {
      return Promise.resolve(
        hasOverride("workflowEvents")
          ? overrides.workflowEvents
          : {
              total: 1,
              items: [
                {
                  id: "workflow-dashboard",
                  user_id: "user-dashboard",
                  session_id: "dashboard-session",
                  occurred_at: "2026-06-03T08:00:00Z",
                  family: "review.required",
                  severity: "action_required",
                  status: "unread",
                  title: "Review required",
                  summary: "A statement needs confirmation before reports are ready.",
                  source_type: "bank_statement",
                  source_id: "statement-dashboard",
                  action_href: "/review",
                  report_impact: "blocked",
                  dedupe_key: "workflow:dashboard",
                  created_at: "2026-06-03T08:00:00Z",
                  updated_at: "2026-06-03T08:00:00Z",
                },
                {
                  id: "workflow-routine-dashboard",
                  user_id: "user-dashboard",
                  session_id: "dashboard-session",
                  occurred_at: "2026-06-03T07:00:00Z",
                  family: "ledger.auto_posted",
                  severity: "success",
                  status: "read",
                  title: "Safe entries posted",
                  summary: "Automation posted high-confidence entries.",
                  source_type: "journal",
                  source_id: "journal-dashboard",
                  action_href: "/journal",
                  report_impact: "ready",
                  dedupe_key: "workflow:routine-dashboard",
                  created_at: "2026-06-03T07:00:00Z",
                  updated_at: "2026-06-03T07:00:00Z",
                },
              ],
              sessions: [
                {
                  id: "dashboard-session",
                  status: "active",
                  title: "Upload-to-report session",
                  summary: "Current upload, processing, review, and report-readiness work.",
                  started_at: "2026-06-03T07:00:00Z",
                  last_event_at: "2026-06-03T08:00:00Z",
                  source_count: 2,
                  primary_state: "needs_action",
                  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
                  event_counts: { unread: 1, action_required: 1, blocked: 0 },
                },
              ],
            },
      )
    }
    if (path.startsWith("/api/reports/income-statement")) return Promise.resolve(hasOverride("income") ? overrides.income : baseIncome)
    if (path.startsWith("/api/income/annualized")) {
      return Promise.resolve(
        hasOverride("annualized") ? overrides.annualized : {
          annualized_salary: 120000,
          annualized_bonus: 15000,
          annualized_dividend: 2400,
          annualized_total: 137400,
          currency: "USD",
          as_of: "2026-05-20",
        },
      )
    }
    if (path.startsWith("/api/assets/restricted")) {
      return Promise.resolve(
        hasOverride("restricted")
          ? overrides.restricted
          : [
              {
                ticker: "SHOP-RSU",
                quantity: "1.000000",
                vesting_schedule: "25% annual vesting",
                unlock_date: "2027-01-01",
                fair_value: 12500,
                currency: "USD",
              },
            ],
      )
    }
    if (path.startsWith("/api/reconciliation/stats")) {
      return Promise.resolve(
        hasOverride("stats") ? overrides.stats : {
          total_transactions: 20,
          matched_transactions: 16,
          unmatched_transactions: 4,
          pending_review: 2,
          auto_accepted: 4,
          match_rate: 80,
          score_distribution: {},
        },
      )
    }
    if (path.startsWith("/api/reconciliation/unmatched")) {
      return Promise.resolve(hasOverride("unmatched") ? overrides.unmatched : { items: [{ id: "u1", description: "Missing txn", txn_date: "2026-01-10", amount: 99 }], total: 1 })
    }
    if (path.startsWith("/api/journal-entries?status_filter=posted")) {
      return Promise.resolve(hasOverride("postedJournal") ? overrides.postedJournal : { items: [{ id: "j1", status: "posted" }], total: 1 })
    }
    if (path.startsWith("/api/journal-entries")) {
      return Promise.resolve(hasOverride("journal") ? overrides.journal : { items: [{ id: "j1", memo: "Rent", entry_date: "2026-01-05", status: "posted" }], total: 1 })
    }
    if (path.startsWith("/api/accounts")) {
      return Promise.resolve(hasOverride("accounts") ? overrides.accounts : { items: [{ id: "a1" }], total: 1 })
    }
    if (path.startsWith("/api/statements")) {
      return Promise.resolve(hasOverride("statements") ? overrides.statements : { items: [{ id: "s1", status: "approved" }], total: 1 })
    }
    if (path.startsWith("/api/reports/trend")) {
      trendCalls += 1
      if (overrides.trendError) return Promise.reject(overrides.trendError)
      if (overrides.rejectTrendAfterFirst && trendCalls > 1) {
        return Promise.reject(new Error("trend fetch failed"))
      }
      return Promise.resolve(overrides.trend ?? { points: [{ period_start: "2026-01-01", amount: 5000 }] })
    }
    return Promise.reject(new Error(`unhandled path ${path}`))
  })
}

async function waitForDashboardAnalyticsReady() {
  await waitFor(() =>
    expect(screen.queryByLabelText("Dashboard analytics loading")).not.toBeInTheDocument(),
  )
}

describe("DashboardPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.12.1 shows loading state before dashboard data resolves", () => {
    mockedApiFetch.mockImplementation(() => new Promise(() => {}))

    render(<DashboardPage />)

    expect(screen.getByText("Loading upload-to-report workflow...")).toBeInTheDocument()
    expect(screen.getByText("Loading dashboard analytics...")).toBeInTheDocument()
  })

  it("AC16.12.2 renders error fallback and retry action on failure", async () => {
    mockedApiFetch.mockRejectedValue(new Error("dashboard failed"))

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Upload to report")).toBeInTheDocument())
    expect(screen.getByText("Workflow status is unavailable. You can still upload files or open reports.")).toBeInTheDocument()
    expect(screen.getByText("Dashboard analytics unavailable")).toBeInTheDocument()
    expect(screen.getByText("dashboard failed")).toBeInTheDocument()
    const callCountBeforeRetry = mockedApiFetch.mock.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Retry analytics" }))
    await waitFor(() => expect(mockedApiFetch.mock.calls.length).toBeGreaterThan(callCountBeforeRetry))
  })

  it("AC16.12.3 renders KPI, chart, activity, and alert sections when API succeeds", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    expect(screen.getByText("Total Assets")).toBeInTheDocument()
    expect(screen.getByText("Total Liabilities")).toBeInTheDocument()
    expect(screen.getByText("Net Assets")).toBeInTheDocument()
    expect(screen.getByText("PieChartMock")).toBeInTheDocument()
    expect(screen.getByText("BarChartMock")).toBeInTheDocument()
    expect(screen.getByText("Recent Entries")).toBeInTheDocument()
    expect(screen.getByText("Unmatched Alerts")).toBeInTheDocument()
  })

  it("AC19.3.6 renders the workflow status feed on the dashboard landing surface", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Workflow status" })).toBeInTheDocument())
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/workflow/status")
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/workflow/events?limit=5")
    expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("Report blocked").length).toBeGreaterThanOrEqual(1)
  })

  it("AC19.4.2 renders the upload-to-report home before secondary dashboard metrics", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Upload to report" })).toBeInTheDocument())
    const workflowHome = screen.getByLabelText("Upload-to-report home")
    const totalAssets = screen.getByText("Total Assets")
    expect(Boolean(workflowHome.compareDocumentPosition(totalAssets) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  })

  it("AC19.4.3 follows workflow next_action for blocker and upload primary CTAs", async () => {
    mockDashboardApi()

    const { unmount } = render(<DashboardPage />)

    await waitFor(() => {
      const uploadHome = within(screen.getByLabelText("Upload-to-report home"))
      expect(uploadHome.getAllByRole("link", { name: /Review required/i })[0]).toHaveAttribute("href", "/review")
    })
    unmount()
    mockedApiFetch.mockReset()

    mockDashboardApi({
      workflowStatus: {
        primary_state: "empty",
        next_action: { type: "upload", count: 0, href: "/statements/upload" },
        report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
        event_counts: { unread: 0, action_required: 0, blocked: 0 },
      },
      workflowEvents: { total: 0, items: [], sessions: [] },
    })

    render(<DashboardPage />)

    await waitFor(() => {
      const uploadHome = within(screen.getByLabelText("Upload-to-report home"))
      expect(uploadHome.getAllByRole("link", { name: /Upload statements/i })[0]).toHaveAttribute("href", "/statements/upload")
    })
  })

  it("AC19.4.4 renders report readiness above analytics with blocker count and link", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByLabelText("Report readiness")).toHaveAttribute("href", "/reports"))
    expect(screen.getAllByText("Report blocked").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("1 blocker")).toBeInTheDocument()
    const readiness = screen.getByLabelText("Report readiness")
    const totalAssets = screen.getByText("Total Assets")
    expect(Boolean(readiness.compareDocumentPosition(totalAssets) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  })

  it("AC19.4.5 shows actionable recent events and summarizes routine automation", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Action required")).toBeInTheDocument())
    expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole("heading", { name: "Routine automation" })).toBeInTheDocument()
    expect(screen.getByText("1 routine event")).toBeInTheDocument()
    expect(screen.getAllByText("Safe entries posted").length).toBeGreaterThanOrEqual(1)
  })

  it("AC19.4.6 keeps upload-to-report home visible when secondary analytics fail", async () => {
    mockDashboardApi({ balanceError: new Error("balance failed") })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Upload to report" })).toBeInTheDocument())
    const uploadHome = within(screen.getByLabelText("Upload-to-report home"))
    expect(uploadHome.getAllByRole("link", { name: /Review required/i })[0]).toHaveAttribute("href", "/review")
    expect(screen.getByText("Dashboard analytics unavailable")).toBeInTheDocument()
    expect(screen.getByText("balance failed")).toBeInTheDocument()
  })

  it("AC11.8.2/AC11.8.6/AC5.6.4 renders Annualized Income card with the four metric labels", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Annualized Income")).toBeInTheDocument())
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByText("Bonus")).toBeInTheDocument()
    expect(screen.getByText("Dividend")).toBeInTheDocument()
    expect(screen.getByText("$137,400")).toBeInTheDocument()
    expect(screen.getByText(/As of May 20, 2026/)).toBeInTheDocument()
  })

  it("AC11.8.4 renders Restricted Holdings separately with vesting metadata", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Restricted Holdings")).toBeInTheDocument())
    expect(screen.getByText("SHOP-RSU")).toBeInTheDocument()
    expect(screen.getByText(/Unlock Jan 1, 2027/)).toBeInTheDocument()
    expect(screen.getByText("$12,500")).toBeInTheDocument()
  })

  it("AC11.8.5 defaults to liquid net worth and refetches when restricted holdings are included", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Include restricted holdings")).toBeInTheDocument())
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/balance-sheet?include_restricted=false")
    expect(screen.getAllByText("$4,000").length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByLabelText("Include restricted holdings"))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/balance-sheet?include_restricted=true"),
    )
    await waitFor(() => expect(screen.getAllByText("$16,500").length).toBeGreaterThanOrEqual(1))
  })

  it("uses empty fallbacks when optional asset APIs return null", async () => {
    mockDashboardApi({ restricted: null })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Restricted Holdings")).toBeInTheDocument())
    expect(screen.getByText("No restricted holdings.")).toBeInTheDocument()
    expect(screen.getAllByText("$4,000").length).toBeGreaterThanOrEqual(1)
  })

  it("uses empty fallbacks when primary dashboard APIs return null", async () => {
    mockDashboardApi({
      balance: null,
      income: null,
      annualized: null,
      stats: null,
      unmatched: null,
      journal: null,
      accounts: null,
      statements: null,
      postedJournal: null,
    })

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    expect(screen.getByText("No assets to chart yet.")).toBeInTheDocument()
    expect(screen.getByText("No income data available.")).toBeInTheDocument()
    expect(screen.getByText("No recent journal entries.")).toBeInTheDocument()
    expect(screen.getByText("No unmatched transactions.")).toBeInTheDocument()
  })

  it("AC16.23.1 renders This Month KPI row with income, expenses, and net from last trend period", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("This Month \u2014 Income")).toBeInTheDocument())
    expect(screen.getByText("This Month \u2014 Expenses")).toBeInTheDocument()
    expect(screen.getByText("This Month \u2014 Net")).toBeInTheDocument()
    expect(screen.getByText("Surplus")).toBeInTheDocument()
  })

  it("AC16.23.2 This Month KPI cards link to income statement report and show deficit", async () => {
    mockDashboardApi({
      income: {
        currency: "USD",
        trends: [{ period_start: "2026-01-01", total_income: 2000, total_expenses: 2500, net_income: -500 }],
      },
    })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("This Month \u2014 Income")).toBeInTheDocument())
    const links = screen.getAllByRole("link", { name: /This Month/i })
    links.forEach((link) => expect(link).toHaveAttribute("href", "/reports/income-statement"))
    expect(screen.getByText("Deficit")).toBeInTheDocument()
  })

  it("AC16.12.4 renders empty-state messages for missing datasets", async () => {
    mockDashboardApi({
      balance: { ...baseBalance, assets: [], total_assets: 0, total_liabilities: 0 },
      income: { currency: "USD", trends: [] },
      restricted: [],
      unmatched: { items: [], total: 0 },
      journal: { items: [], total: 0 },
      trend: { points: [] },
      accounts: { items: [], total: 0 },
      statements: { items: [], total: 0 },
      postedJournal: { items: [], total: 0 },
    })

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    expect(screen.getByText(/No trend data/)).toBeInTheDocument()
    expect(screen.getByText("No assets to chart yet.")).toBeInTheDocument()
    expect(screen.getByText("No income data available.")).toBeInTheDocument()
    expect(screen.getByText("No restricted holdings.")).toBeInTheDocument()
    expect(screen.getByText("No recent journal entries.")).toBeInTheDocument()
    expect(screen.getByText("No unmatched transactions.")).toBeInTheDocument()
  })

  it("AC16.23.6 data health bar uses matched_transactions/total_transactions not auto_accepted", async () => {
    mockDashboardApi()

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Data health")).toBeInTheDocument())
    expect(screen.getByText("80%")).toBeInTheDocument()
    expect(screen.queryByText("20%")).not.toBeInTheDocument()
    expect(screen.getByText("16 matched")).toBeInTheDocument()
  })

  it("renders account selector and handles trend error when multiple assets exist", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined)
    mockDashboardApi({
      rejectTrendAfterFirst: true,
      balance: {
        ...baseBalance,
        assets: [
          { account_id: "a1", name: "Cash", amount: 5000 },
          { account_id: "a2", name: "Savings", amount: 3000 },
        ],
        total_assets: 8000,
      },
    })

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    const selector = screen.getByRole("combobox") as HTMLSelectElement
    expect(selector).toBeInTheDocument()
    expect(screen.getByText("Top Asset")).toBeInTheDocument()
    expect(screen.getByText("Savings")).toBeInTheDocument()

    fireEvent.change(selector, { target: { value: "a2" } })

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/trend?account_id=a2&period=monthly"))
    expect(consoleError).toHaveBeenCalledWith("Failed to fetch trend data:", expect.any(Error))
    consoleError.mockRestore()
  })

  it("keeps the dashboard usable when trend fetch fails", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined)
    mockDashboardApi({ trendError: new Error("trend failed") })

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    await waitFor(() => expect(screen.getByText(/No trend data/)).toBeInTheDocument())
    expect(consoleErrorSpy).toHaveBeenCalledWith("Failed to fetch trend data:", expect.any(Error))

    consoleErrorSpy.mockRestore()
  })

  it("AC16.12.17 AC16.12.18 renders first-time onboarding with core workflow links", async () => {
    mockDashboardApi({
      balance: { ...baseBalance, assets: [], total_assets: 0, total_liabilities: 0 },
      income: { currency: "USD", trends: [] },
      restricted: [],
      unmatched: { items: [], total: 0 },
      journal: { items: [], total: 0 },
      accounts: { items: [], total: 0 },
      statements: { items: [], total: 0 },
      postedJournal: { items: [], total: 0 },
      trend: { points: [] },
    })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByLabelText("Getting started")).toBeInTheDocument())
    expect(screen.getByText("Build your first accurate financial view")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Add your first account/i })).toHaveAttribute("href", "/accounts")
    expect(screen.getByRole("link", { name: /Upload a bank statement/i })).toHaveAttribute("href", "/statements")
    expect(screen.getByRole("link", { name: /Review and approve/i })).toHaveAttribute("href", "/review")
  })

  it("AC16.12.17 keeps onboarding visible with partial progress markers", async () => {
    mockDashboardApi({
      balance: { ...baseBalance, assets: [], total_assets: 0, total_liabilities: 0 },
      income: { currency: "USD", trends: [] },
      restricted: [],
      unmatched: { items: [], total: 0 },
      journal: { items: [], total: 0 },
      accounts: { items: [{ id: "a1" }], total: 1 },
      statements: { items: [{ id: "s1", status: "parsed" }], total: 1 },
      postedJournal: { items: [], total: 0 },
      trend: { points: [] },
    })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByLabelText("Getting started")).toBeInTheDocument())
    expect(screen.getAllByText("Done")).toHaveLength(2)
    expect(screen.getByText("Next")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Review and approve/i })).toHaveAttribute("href", "/review")
  })

  it("AC16.12.19 hides first-time onboarding after approved statement and posted journal entry exist", async () => {
    mockDashboardApi({
      balance: { ...baseBalance, assets: [{ account_id: "a1", name: "Cash", amount: 5000 }], total_liabilities: 0 },
      income: { currency: "USD", trends: [] },
      unmatched: { items: [], total: 0 },
      journal: { items: [{ id: "j1", memo: "Approved import", entry_date: "2026-01-05", status: "posted" }], total: 1 },
      accounts: { items: [{ id: "a1" }], total: 1 },
      statements: { items: [{ id: "s1", status: "approved" }], total: 1 },
      postedJournal: { items: [{ id: "j1", status: "posted" }], total: 1 },
    })

    render(<DashboardPage />)

    await waitForDashboardAnalyticsReady()
    expect(screen.queryByLabelText("Getting started")).not.toBeInTheDocument()
    expect(screen.getByText("Total Assets")).toBeInTheDocument()
  })
})
