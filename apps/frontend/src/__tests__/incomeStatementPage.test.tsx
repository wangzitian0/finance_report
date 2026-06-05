import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import IncomeStatementPage from "@/app/(main)/reports/income-statement/page"
import { apiDownload, apiFetch } from "@/lib/api"

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
  apiDownload: vi.fn(),
  apiFetch: vi.fn(),
}))

describe("IncomeStatementPage", () => {
  const mockedApiDownload = vi.mocked(apiDownload)
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiDownload.mockReset()
    mockedApiFetch.mockReset()
  })

  it("AC16.14.4 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("income failed"))

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("income failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(mockedApiFetch).toHaveBeenCalled()
  })

  it("AC16.14.5 / test_AC8_13_48 renders string KPI cards and category lists", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "5000" }],
      expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "1200" }],
      total_income: "5000",
      total_expenses: "1200",
      net_income: "3800",
      fx_warnings: [{ type: "missing_average_rate", from_currency: "USD", to_currency: "SGD", date: "2026-01-31" }],
      trends: [{ period_start: "2026-01-01", period_end: "2026-01-31", total_income: "5000", total_expenses: "1200", net_income: "3800" }],
      filters_applied: { tags: null, account_type: null },
    })

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())
    expect(screen.getByText("Total Income")).toBeInTheDocument()
    expect(screen.getByText("Total Expenses")).toBeInTheDocument()
    expect(screen.getByText("Net Income")).toBeInTheDocument()
    expect(screen.getByText("BarChartMock")).toBeInTheDocument()
    expect(screen.getByText("Partial FX data used")).toBeInTheDocument()
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByText("Rent")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt=")
    )
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard")
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument()
    expect(screen.getByText("Total Income").closest("div")).toHaveTextContent("5,000.00")
    expect(screen.getByText("Total Expenses").closest("div")).toHaveTextContent("1,200.00")
    expect(screen.getByText("Net Income").closest("div")).toHaveTextContent("3,800.00")
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
    await waitFor(() => {
      const lastCall = mockedApiFetch.mock.calls.at(-1)?.[0]
      expect(lastCall).toContain("tags=business")
    })

    const clearAllButton = await screen.findByRole("button", { name: "Clear all" })
    expect(clearAllButton).toBeInTheDocument()

    fireEvent.click(clearAllButton)
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument()
    })
  })

  it("AC16.14.10 shows active filters and empty-state messages", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "USD",
      income: [],
      expenses: [],
      total_income: 0,
      total_expenses: 0,
      net_income: 0,
      trends: [],
      filters_applied: { tags: ["business"], account_type: "INCOME" },
    })

    render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("Active filters:")).toBeInTheDocument())
    expect(screen.getByText("INCOME")).toBeInTheDocument()
    expect(screen.getByText("business")).toBeInTheDocument()
    expect(screen.getByText("No trend data yet.")).toBeInTheDocument()
    expect(screen.getByText("No income categories.")).toBeInTheDocument()
    expect(screen.getByText("No expense categories.")).toBeInTheDocument()
  })

  it("AC16.14.11 / test_AC8_13_48 refetches when account type, tags, and dates change", async () => {
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
      filters_applied: { tags: null, account_type: null },
    })

    const { container } = render(<IncomeStatementPage />)

    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())
    const selects = screen.getAllByRole("combobox")
    fireEvent.change(selects[1], { target: { value: "INCOME" } })

    await waitFor(() => {
      const lastCall = mockedApiFetch.mock.calls.at(-1)?.[0]
      expect(lastCall).toContain("/api/reports/income-statement?")
      expect(lastCall).toContain("account_type=INCOME")
    })
    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())

    const dateInputs = container.querySelectorAll('input[type="date"]')
    fireEvent.change(dateInputs[0], { target: { value: "2026-01-15" } })
    await waitFor(() => {
      const lastCall = mockedApiFetch.mock.calls.at(-1)?.[0]
      expect(lastCall).toContain("start_date=2026-01-15")
    })
    await waitFor(() => expect(screen.getByText("Income Statement")).toBeInTheDocument())
    fireEvent.change(container.querySelectorAll('input[type="date"]')[1], { target: { value: "2026-02-15" } })

    await waitFor(() => {
      const lastCall = mockedApiFetch.mock.calls.at(-1)?.[0]
      expect(lastCall).toContain("/api/reports/income-statement?")
      expect(lastCall).toContain("account_type=INCOME")
      expect(lastCall).toContain("start_date=2026-01-15")
      expect(lastCall).toContain("end_date=2026-02-15")
    })
  })
})
