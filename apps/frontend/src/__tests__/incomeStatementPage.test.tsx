import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import IncomeStatementPage from "@/app/(main)/reports/income-statement/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/components/charts/BarChart", () => ({
  BarChart: () => <div>BarChartMock</div>,
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"] }),
}))

vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiFetch: vi.fn(),
}))

describe("IncomeStatementPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.14.4 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("income failed"))

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("income failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(mockedApiFetch).toHaveBeenCalled()
  })

  it("AC16.14.5 renders KPI cards and category lists", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: 5000 }],
      expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: 1200 }],
      total_income: 5000,
      total_expenses: 1200,
      net_income: 3800,
      trends: [{ period_start: "2026-01-01", period_end: "2026-01-31", total_income: 5000, total_expenses: 1200, net_income: 3800 }],
      filters_applied: { tags: null, account_type: null },
    })

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())
    expect(screen.getByText("Total Income")).toBeInTheDocument()
    expect(screen.getByText("Total Expenses")).toBeInTheDocument()
    expect(screen.getByText("Net Income")).toBeInTheDocument()
    expect(screen.getByText("BarChartMock")).toBeInTheDocument()
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByText("Rent")).toBeInTheDocument()
  })

  it("AC16.14.6 supports selecting and clearing tags", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      income: [],
      expenses: [],
      total_income: 0,
      total_expenses: 0,
      net_income: 0,
      trends: [],
      filters_applied: { tags: ["business"], account_type: "INCOME" },
    })

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Business" }))

    const clearAllButton = await screen.findByRole("button", { name: "Clear all" })
    expect(clearAllButton).toBeInTheDocument()

    fireEvent.click(clearAllButton)
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument()
    })
  })
})
