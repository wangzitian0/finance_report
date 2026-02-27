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

    await waitFor(() => expect(screen.getByText("Welcome to Finance Report")).toBeInTheDocument())
    expect(screen.getByText("dashboard failed")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Retry Connection" }))
    expect(mockedApiFetch).toHaveBeenCalled()
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
    expect(screen.getByText("No trend data")).toBeInTheDocument()
    expect(screen.getByText("No assets to chart yet.")).toBeInTheDocument()
    expect(screen.getByText("No income data available.")).toBeInTheDocument()
    expect(screen.getByText("No recent journal entries.")).toBeInTheDocument()
    expect(screen.getByText("No unmatched transactions.")).toBeInTheDocument()
  })
})
