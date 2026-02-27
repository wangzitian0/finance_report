import { render, screen, waitFor } from "@testing-library/react"
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

  it("AC16.14.8 renders summary and activity sections", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [{ category: "operating", subcategory: "Sales", amount: 1000, description: "Main ops" }],
      investing: [{ category: "investing", subcategory: "ETF", amount: -300, description: null }],
      financing: [{ category: "financing", subcategory: "Loan", amount: 200, description: null }],
      summary: {
        operating_activities: 1000,
        investing_activities: -300,
        financing_activities: 200,
        net_cash_flow: 900,
        beginning_cash: 5000,
        ending_cash: 5900,
      },
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Net Cash Flow")).toBeInTheDocument()
    expect(screen.getByText("Operating Activities")).toBeInTheDocument()
    expect(screen.getByText("Investing Activities")).toBeInTheDocument()
    expect(screen.getByText("Financing Activities")).toBeInTheDocument()
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
})
