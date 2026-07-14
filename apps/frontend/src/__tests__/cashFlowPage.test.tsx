import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CashFlowPage from "@/app/(main)/reports/cash-flow/page"
import { apiDownload, apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}))

vi.mock("@/components/charts/SankeyChart", () => ({
  SankeyChart: () => <div>SankeyChartMock</div>,
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD", "EUR"], loading: false }),
}))

vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiDownload: vi.fn(),
  apiFetch: vi.fn(),
}))

describe("CashFlowPage", () => {
  const mockedApiDownload = vi.mocked(apiDownload)
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiDownload.mockReset()
    mockedApiFetch.mockReset()
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:cash-flow-export"),
      revokeObjectURL: vi.fn(),
    }))
  })

  // AC-reporting.fe-report-surfaces.16
  it("AC16.14.7 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("cashflow failed"))

    const { container } = render(<CashFlowPage />)

    expect(screen.getByRole("status", { name: "Loading cash flow" })).toHaveAttribute("aria-busy", "true")
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(10)
    expect(container.querySelector(".animate-spin")).toBeNull()

    await waitFor(() => expect(screen.getByText("cashflow failed")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
  })

  // AC-reporting.fe-report-surfaces.17
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
      fx_warnings: [{ type: "spot_rate_fallback", from_currency: "EUR", to_currency: "SGD", fallback_date: "2026-01-30" }],
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Net Cash Flow")).toBeInTheDocument()
    expect(screen.getByText("Operating Activities")).toBeInTheDocument()
    expect(screen.getByText("Investing Activities")).toBeInTheDocument()
    expect(screen.getByText("Financing Activities")).toBeInTheDocument()
    expect(screen.getByText("Partial FX data used")).toBeInTheDocument()
    expect(screen.getByText("Sales")).toBeInTheDocument()
    expect(screen.getByText("Main ops")).toBeInTheDocument()

    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt=")
    )
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument()

    const netCashFlowCard = screen.getByText("Net Cash Flow").closest("div")
    const beginningCashCard = screen.getByText("Beginning Cash").closest("div")
    const endingCashCard = screen.getByText("Ending Cash").closest("div")
    expect(netCashFlowCard).toHaveTextContent("900.00")
    expect(beginningCashCard).toHaveTextContent("5,000.00")
    expect(endingCashCard).toHaveTextContent("5,900.00")

    // AC22.7.3: beginning + net = ending ties, so it shows a reconciled state.
    const reconciliation = screen.getByLabelText("Cash reconciliation")
    expect(reconciliation).toHaveTextContent("✓ Reconciles")
  })

  // AC-reporting.fe-ia-reports.12
  it("AC22.7.3 flags cash that does not tie (beginning + net != ending)", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0",
        investing_activities: "0",
        financing_activities: "0",
        net_cash_flow: "900",
        beginning_cash: "5000",
        ending_cash: "6500", // expected 5900, so it drifts by 600
      },
    })

    render(<CashFlowPage />)

    const reconciliation = await screen.findByLabelText("Cash reconciliation")
    expect(reconciliation).toHaveTextContent("⚠ Does not tie")
    expect(screen.getByText(/differs from the reported ending/i)).toBeInTheDocument()
    // The drift is shown as a positive amount with an explicit direction, never
    // a confusing negative (reported 6500 > expected 5900).
    expect(reconciliation).toHaveTextContent("the reported ending is higher than expected")
    expect(reconciliation).not.toHaveTextContent("-")
  })

  // AC-reporting.fe-ia-reports.10
  it("AC22.7.1 drills a cash-flow amount down to its account lineage", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/cash-flow")) {
        return Promise.resolve({
          start_date: "2026-01-01",
          end_date: "2026-02-01",
          currency: "SGD",
          operating: [
            { category: "operating", subcategory: "Salary", amount: "500", description: "Inflow - Salary", account_id: "acc-salary" },
          ],
          investing: [],
          financing: [],
          summary: {
            operating_activities: "500", investing_activities: "0", financing_activities: "0",
            net_cash_flow: "500", beginning_cash: "1000", ending_cash: "1500",
          },
        })
      }
      if (path.startsWith("/api/reports/account-lineage")) {
        return Promise.resolve({
          account_id: "acc-salary", account_name: "Salary", account_type: "INCOME",
          currency: "SGD", as_of_date: "2026-02-01", start_date: "2026-01-01",
          total: "500.00", lines: [],
        })
      }
      return Promise.resolve({})
    })

    render(<CashFlowPage />)

    const amount = await screen.findByRole("button", { name: /View source transactions for Salary/i })
    fireEvent.click(amount)

    const dialog = await screen.findByRole("dialog")
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/reports/account-lineage?account_id=acc-salary"),
      ),
    )

    // Closing the drawer clears the drill target.
    fireEvent.click(within(dialog).getByRole("button", { name: /close/i }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  // AC-reporting.fe-report-surfaces.18
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

  it("AC5.17.1 downloads cash-flow CSV through authenticated apiDownload", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0",
        investing_activities: "0",
        financing_activities: "0",
        net_cash_flow: "0",
        beginning_cash: "0",
        ending_cash: "0",
      },
    })
    mockedApiDownload.mockResolvedValue({
      blob: new Blob(["section,account,amount\n"], { type: "text/csv" }),
      filename: "cash-flow-2026-01-01-to-2026-01-31.csv",
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-01-01" } })
    await waitFor(() => expect(screen.getByLabelText("End date")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-01-31" } })
    await waitFor(() => expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }))

    await waitFor(() =>
      expect(mockedApiDownload).toHaveBeenCalledWith(
        expect.stringContaining("/api/reports/export?report_type=cash-flow"),
      ),
    )
    expect(String(mockedApiDownload.mock.calls[0][0])).toContain("start_date=2026-01-01")
    expect(String(mockedApiDownload.mock.calls[0][0])).toContain("end_date=2026-01-31")
    expect(String(mockedApiDownload.mock.calls[0][0])).toContain("currency=SGD")
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
