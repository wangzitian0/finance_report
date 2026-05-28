import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CashFlowPage from "@/app/(main)/reports/cash-flow/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/components/charts/SankeyChart", () => ({
  SankeyChart: () => <div>SankeyChartMock</div>,
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD", "EUR"], loading: false }),
}))

vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiFetch: vi.fn(),
}))

describe("CashFlowPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.14.7 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("cashflow failed"))

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("cashflow failed")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
  })

  it("AC16.14.8 / test_AC8_13_48 renders string summary and activity sections", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [{ category: "operating", subcategory: "Sales", amount: "1000", description: "Main ops" }],
      investing: [{ category: "investing", subcategory: "ETF", amount: "-300", description: null }],
      financing: [{ category: "financing", subcategory: "Loan", amount: "200", description: null }],
      summary: {
        operating_activities: "1000",
        investing_activities: "-300",
        financing_activities: "200",
        net_cash_flow: "900",
        beginning_cash: "5000",
        ending_cash: "5900",
      },
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Net Cash Flow")).toBeInTheDocument()
    expect(screen.getByText("Operating Activities")).toBeInTheDocument()
    expect(screen.getByText("Investing Activities")).toBeInTheDocument()
    expect(screen.getByText("Financing Activities")).toBeInTheDocument()
    expect(screen.getByText("Sales")).toBeInTheDocument()
    expect(screen.getByText("Main ops")).toBeInTheDocument()

    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt=")
    )
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard")
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      expect.stringContaining("/api/reports/export?report_type=cash-flow")
    )

    const netCashFlowCard = screen.getByText("Net Cash Flow").closest("div")
    const beginningCashCard = screen.getByText("Beginning Cash").closest("div")
    const endingCashCard = screen.getByText("Ending Cash").closest("div")
    expect(netCashFlowCard).toHaveTextContent("900.00")
    expect(beginningCashCard).toHaveTextContent("5,000.00")
    expect(endingCashCard).toHaveTextContent("5,900.00")
  })

  it("AC16.14.9 renders sankey chart when summary exists", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: 0,
        investing_activities: 0,
        financing_activities: 0,
        net_cash_flow: 0,
        beginning_cash: 0,
        ending_cash: 0,
      },
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("SankeyChartMock")).toBeInTheDocument())
  })

  it("AC16.14.10 / test_AC8_13_48 refetches when filters and dates change", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "USD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: 0,
        investing_activities: 0,
        financing_activities: 0,
        net_cash_flow: 0,
        beginning_cash: 0,
        ending_cash: 0,
      },
    })

    const { container } = render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "USD" } })

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(
        expect.stringContaining("currency=USD")
      )
    )
    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())

    const dateInputs = container.querySelectorAll('input[type="date"]')
    expect(dateInputs).toHaveLength(2)
    fireEvent.change(dateInputs[0], { target: { value: "2026-01-15" } })
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(expect.stringContaining("start_date=2026-01-15")),
    )
    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    fireEvent.change(container.querySelectorAll('input[type="date"]')[1], { target: { value: "2026-02-15" } })
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(expect.stringContaining("end_date=2026-02-15")),
    )
    const lastCall = String(mockedApiFetch.mock.calls.at(-1)?.[0])
    expect(lastCall).toContain("start_date=2026-01-15")
    expect(lastCall).toContain("end_date=2026-02-15")
    expect(screen.getAllByText("No items in this category.")).toHaveLength(3)
  })
})
