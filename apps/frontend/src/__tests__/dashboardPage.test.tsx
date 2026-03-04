import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import DashboardPage from "@/app/(main)/dashboard/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
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

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("DashboardPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.12.1 shows loading state before dashboard data resolves", () => {
    mockedApiFetch.mockImplementation(() => new Promise(() => {}))

    render(<DashboardPage />)

    expect(screen.getByText("Loading dashboard...")).toBeInTheDocument()
  })

  it("AC16.12.2 renders error fallback and retry action on failure", async () => {
    mockedApiFetch.mockRejectedValue(new Error("dashboard failed"))

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Unable to Load Dashboard")).toBeInTheDocument())
    expect(screen.getByText("dashboard failed")).toBeInTheDocument()
    const callCountBeforeRetry = mockedApiFetch.mock.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Retry Connection" }))
    await waitFor(() => expect(mockedApiFetch.mock.calls.length).toBeGreaterThan(callCountBeforeRetry))
  })

  it("AC16.12.3 renders KPI and chart sections when API succeeds", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        assets: [{ account_id: "a1", name: "Cash", amount: 5000 }],
        total_assets: 5000,
        total_liabilities: 1000,
        currency: "USD",
        as_of_date: "2026-02-01",
        is_balanced: true,
      })
      .mockResolvedValueOnce({
        trends: [{ period_start: "2026-01-01", total_income: 3000, total_expenses: 1200 }],
      })
      .mockResolvedValueOnce({
        auto_accepted: 8,
        pending_review: 2,
        unmatched_transactions: 1,
      })
      .mockResolvedValueOnce({
        items: [{ id: "u1", description: "Missing txn", txn_date: "2026-01-10", amount: 99 }],
      })
      .mockResolvedValueOnce({
        items: [{ id: "j1", memo: "Rent", entry_date: "2026-01-05", status: "posted" }],
      })
      .mockResolvedValueOnce({
        points: [{ period_start: "2026-01-01", amount: 5000 }],
      })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Dashboard")).toBeInTheDocument())
    expect(screen.getByText("Total Assets")).toBeInTheDocument()
    expect(screen.getByText("Total Liabilities")).toBeInTheDocument()
    expect(screen.getByText("Net Assets")).toBeInTheDocument()
    expect(screen.getByText("PieChartMock")).toBeInTheDocument()
    expect(screen.getByText("BarChartMock")).toBeInTheDocument()
    expect(screen.getByText("Recent Entries")).toBeInTheDocument()
    expect(screen.getByText("Unmatched Alerts")).toBeInTheDocument()
  })

  it("AC16.23.1 renders This Month KPI row with income, expenses, and net from last trend period", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        assets: [{ account_id: "a1", name: "Cash", amount: 5000 }],
        total_assets: 5000,
        total_liabilities: 1000,
        currency: "USD",
        as_of_date: "2026-02-01",
        is_balanced: true,
      })
      .mockResolvedValueOnce({
        currency: "USD",
        trends: [
          { period_start: "2025-12-01", total_income: 1000, total_expenses: 800, net_income: 200 },
          { period_start: "2026-01-01", total_income: 3500, total_expenses: 1200, net_income: 2300 },
        ],
      })
      .mockResolvedValueOnce({ auto_accepted: 0, pending_review: 0, unmatched_transactions: 0 })
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ points: [] })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Dashboard")).toBeInTheDocument())
    expect(screen.getByText("This Month \u2014 Income")).toBeInTheDocument()
    expect(screen.getByText("This Month \u2014 Expenses")).toBeInTheDocument()
    expect(screen.getByText("This Month \u2014 Net")).toBeInTheDocument()
    expect(screen.getByText("Surplus")).toBeInTheDocument()
  })

  it("AC16.23.2 This Month KPI cards link to income statement report and show deficit when net is negative", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        assets: [],
        total_assets: 0,
        total_liabilities: 0,
        currency: "USD",
        as_of_date: "2026-02-01",
        is_balanced: true,
      })
      .mockResolvedValueOnce({
        currency: "USD",
        trends: [{ period_start: "2026-01-01", total_income: 2000, total_expenses: 2500, net_income: -500 }],
      })
      .mockResolvedValueOnce({ auto_accepted: 0, pending_review: 0, unmatched_transactions: 0 })
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("This Month \u2014 Income")).toBeInTheDocument())
    const links = screen.getAllByRole("link", { name: /This Month/i })
    expect(links.length).toBeGreaterThanOrEqual(1)
    links.forEach((link) => expect(link).toHaveAttribute("href", "/reports/income-statement"))
    expect(screen.getByText("Deficit")).toBeInTheDocument()
  })

  it("AC16.12.4 renders empty-state messages for missing datasets", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        assets: [],
        total_assets: 0,
        total_liabilities: 0,
        currency: "USD",
        as_of_date: "2026-02-01",
        is_balanced: true,
      })
      .mockResolvedValueOnce({ trends: [] })
      .mockResolvedValueOnce({ auto_accepted: 0, pending_review: 0, unmatched_transactions: 0 })
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Dashboard")).toBeInTheDocument())
    expect(screen.getByText(/No trend data/)).toBeInTheDocument()
    expect(screen.getByText("No assets to chart yet.")).toBeInTheDocument()
    expect(screen.getByText("No income data available.")).toBeInTheDocument()
    expect(screen.getByText("No recent journal entries.")).toBeInTheDocument()
    expect(screen.getByText("No unmatched transactions.")).toBeInTheDocument()
  })

  it("AC16.23.6 data health bar uses matched_transactions/total_transactions not auto_accepted", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        assets: [],
        total_assets: 0,
        total_liabilities: 0,
        currency: "USD",
        as_of_date: "2026-02-01",
        is_balanced: true,
      })
      .mockResolvedValueOnce({ currency: "USD", trends: [] })
      .mockResolvedValueOnce({
        total_transactions: 20,
        matched_transactions: 16,
        unmatched_transactions: 4,
        pending_review: 2,
        auto_accepted: 4,
        match_rate: 80,
      })
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText("Data health")).toBeInTheDocument())
    // Should show 80% (= 16/20), NOT 20% (= 4/20 from auto_accepted)
    expect(screen.getByText("80%")).toBeInTheDocument()
    expect(screen.queryByText("20%")).not.toBeInTheDocument()
    // Label shows matched count from matched_transactions
    expect(screen.getByText("16 matched")).toBeInTheDocument()
  })

})