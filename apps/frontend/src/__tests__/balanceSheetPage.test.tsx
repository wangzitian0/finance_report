import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"
import { apiOperation, apiOperationDownload } from "@/lib/api-client"

import { balanceSheetVector } from "./fixtures/apiVectors"
import { setTestUrl } from "./helpers/nextNavigation"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"] }),
}))

vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}))

vi.mock("@/lib/api-client", () => ({
  API_URL: "http://localhost:8000",
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}))

const BalanceSheetPage = () => <ReportsPage />
const balanceSheetCalls = () =>
  vi.mocked(apiOperation).mock.calls.filter(([operationId]) => operationId === "balance_sheet_reports_balance_sheet_get")

describe("BalanceSheetPage", () => {
  const mockedApiDownload = vi.mocked(apiOperationDownload)
  const mockedApiFetch = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiDownload.mockReset()
    mockedApiFetch.mockReset()
    setTestUrl("/reports?tab=balance-sheet")
  })

  // AC-reporting.fe-report-surfaces.10
  it("AC16.14.1 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("balance failed"))

    const { container } = render(<BalanceSheetPage />)

    expect(screen.getByRole("status", { name: "Loading balance sheet" })).toHaveAttribute("aria-busy", "true")
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(12)
    expect(container.querySelector(".animate-spin")).toBeNull()

    await waitFor(() => expect(screen.getByText("balance failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(mockedApiFetch).toHaveBeenCalled()
  })

  // AC-reporting.fe-report-surfaces.11
  // AC-reporting.fe-viz-reports.8 / AC-reporting.fe-viz-reports.9
  it("AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date", async () => {
    // AC-reporting.api-vectors.2 (#1827): the mock is the committed
    // backend-owned conformance vector, not hand-written JSON — a
    // regenerated breaking shape reds this test (G-contract-reddens).
    const vector = balanceSheetVector()
    mockedApiFetch.mockResolvedValue(vector)

    const { container } = render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument())
    expect(screen.getByRole("heading", { name: "Assets", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Liabilities", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Equity", level: 2 })).toBeInTheDocument()
    // The vector carries the REAL served fx-warning keys
    // (base_currency/quote_currency) — the pre-vector hand-mock's
    // from_currency/to_currency had silently drifted from the backend.
    expect(screen.getByText("Partial FX data used")).toBeInTheDocument()
    expect(screen.getByText("Balance Equation Detail")).toBeInTheDocument()
    expect(screen.getByText("CTA Adjustment")).toBeInTheDocument()
    // The default scope includes restricted holdings (#2645).
    expect(screen.getByText("Included")).toBeInTheDocument()
    // Vector value assertions: the wire keeps decimal STRINGS end to end.
    expect(vector.total_assets).toBe("9500.00")
    expect(screen.getByText("Vector Bank Checking")).toBeInTheDocument()
    expect(screen.getByText("Vector Credit Card")).toBeInTheDocument()
    expect(screen.getByText("Vector Opening Balances")).toBeInTheDocument()
    expect(screen.getByText("Manual")).toHaveAccessibleName("Provenance: Manual")
    expect(screen.getByText("Derived")).toHaveAccessibleName("Provenance: Derived")
    const imported = screen.getAllByText("Imported")
    expect(imported).toHaveLength(2)
    expect(imported[0]).toHaveAccessibleName("Provenance: Imported")
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "balance_sheet_reports_balance_sheet_get",
      expect.objectContaining({ query: expect.objectContaining({ include_restricted: true }) }),
    )
    expect(screen.getAllByText(/Total:/)).toHaveLength(3)

    fireEvent.click(screen.getByLabelText("Include restricted holdings"))
    await waitFor(() =>
      expect(balanceSheetCalls().at(-1)?.[1]).toEqual(
        expect.objectContaining({ query: expect.objectContaining({ include_restricted: false }) }),
      ),
    )

    // The dimension bar moves the balance sheet date to the end of the previous period.
    fireEvent.click(screen.getByRole("button", { name: "Period 1M" }))
    fireEvent.click(screen.getByRole("button", { name: "Previous period" }))
    const today = new Date()
    const lastDayOfPreviousMonth = new Date(today.getFullYear(), today.getMonth(), 0)
    const expectedDate = `${lastDayOfPreviousMonth.getFullYear()}-${String(lastDayOfPreviousMonth.getMonth() + 1).padStart(2, "0")}-${String(lastDayOfPreviousMonth.getDate()).padStart(2, "0")}`
    await waitFor(() =>
      expect(balanceSheetCalls().at(-1)?.[1]).toEqual(
        expect.objectContaining({ query: expect.objectContaining({ as_of_date: expectedDate }) }),
      ),
    )
    expect(container.querySelector('input[type="date"]')).toBeNull()
    expect(screen.getByRole("button", { name: "Period 1M" })).toHaveAttribute("aria-pressed", "true")
  })

  it("AC8.13.42 honors include_restricted=true from the balance-sheet URL", async () => {
    // The old route /reports/balance-sheet?include_restricted=true redirects here with its query.
    setTestUrl("/reports?tab=balance-sheet&include_restricted=true")
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [
        { account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000", provenance: "imported" },
        {
          account_id: "restricted-root",
          name: "Four Asset ESOP",
          type: "ASSET",
          parent_id: null,
          amount: "42000",
          provenance: "manual",
        },
      ],
      liabilities: [],
      equity: [],
      total_assets: "43000",
      total_liabilities: "0",
      total_equity: "43000",
      equation_delta: "0",
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "balance_sheet_reports_balance_sheet_get",
        expect.objectContaining({ query: expect.objectContaining({ include_restricted: true }) }),
      ),
    )
    expect(await screen.findByLabelText("Include restricted holdings")).toBeChecked()
  })

  // AC-reporting.net-worth-scope.6
  it("#2645 shows manual valuations on their own equity line, never in the FX and CTA line", async () => {
    // The #2645 data in the full scope, with a small FX gain: an SGD bank account and the
    // property, mortgage and ESOP valuations (1,200,000 + 42,000 - 650,000 = 592,000).
    mockedApiFetch.mockImplementation((operationId: string) => {
      if (operationId === "balance_sheet_reports_balance_sheet_get") {
        return Promise.resolve({
          as_of_date: "2026-10-23",
          currency: "SGD",
          assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20385.65" }],
          liabilities: [{ account_id: "loan", name: "Valuation: Condo loan (mortgage balance)", type: "LIABILITY", parent_id: null, amount: "650000.00" }],
          equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }],
          total_assets: "1262385.65",
          total_liabilities: "650000.00",
          total_equity: "15000.00",
          net_income: "5360.65",
          unrealized_fx_gain_loss: "25.00",
          cta_adjustment: "0.00",
          net_worth_adjustment_gain_loss: "592000.00",
          excluded_holdings: [],
          equation_delta: "0.00",
          is_balanced: true,
        })
      }
      return Promise.resolve({ currency: "SGD", granularity: "monthly", points: [] })
    })

    render(<BalanceSheetPage />)

    expect(await screen.findByTestId("equity-fx-cta")).toHaveTextContent("FX and translation (CTA):SGD 25.00")
    expect(screen.getByTestId("equity-valuations")).toHaveTextContent("Manual and market valuations:SGD 592,000.00")
    expect(screen.queryByText(/FX\/CTA/)).toBeNull()
    // The equity side total equals the net worth: 1,262,385.65 - 650,000.00.
    const equity = screen.getByRole("heading", { name: "Equity", level: 2 }).closest("div")!
    expect(within(equity).getByText("Total:").nextElementSibling).toHaveTextContent("SGD 612,385.65")
    expect(screen.queryByTestId("excluded-holdings-note")).toBeNull()
  })

  // AC-reporting.net-worth-scope.7
  it("#2645 names each class and amount that the scope without restricted holdings excludes", async () => {
    setTestUrl("/reports?tab=balance-sheet&include_restricted=false")
    mockedApiFetch.mockImplementation((operationId: string) => {
      if (operationId === "balance_sheet_reports_balance_sheet_get") {
        return Promise.resolve({
          as_of_date: "2026-10-23",
          currency: "SGD",
          assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20360.65" }],
          liabilities: [],
          equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }],
          total_assets: "20360.65",
          total_liabilities: "0.00",
          total_equity: "15000.00",
          net_income: "5360.65",
          excluded_holdings: [
            { asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00" },
            { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00" },
          ],
          equation_delta: "0.00",
          is_balanced: true,
        })
      }
      return Promise.resolve({ currency: "SGD", granularity: "monthly", points: [] })
    })

    render(<BalanceSheetPage />)

    expect(await screen.findByTestId("excluded-holdings-note")).toHaveTextContent(
      "Excludes restricted and illiquid holdings:Real Estate SGD 550,000.00 (net of SGD 650,000.00 liabilities)Restricted Comp SGD 42,000.00",
    )
    expect(screen.getByText("Excluded")).toBeInTheDocument()
    expect(screen.queryByTestId("equity-valuations")).toBeNull()
  })

  it("AC22.3.4 opens the source drill-down when an amount is clicked", async () => {
    mockedApiFetch.mockImplementation((operationId: string) => {
      if (operationId === "account_lineage_reports_account_lineage_get") {
        return Promise.resolve({
          account_id: "a-root",
          account_name: "Cash",
          account_type: "ASSET",
          currency: "SGD",
          as_of_date: "2026-02-01",
          start_date: null,
          total: "1000.00",
          lines: [
            {
              journal_line_id: "88888888-8888-4888-8888-888888888888",
              journal_entry_id: "99999999-9999-4999-8999-999999999999",
              entry_date: "2026-01-15",
              memo: "Opening deposit",
              direction: "DEBIT",
              original_amount: "1000.00",
              original_currency: "SGD",
              amount: "1000.00",
            },
          ],
        })
      }
      return Promise.resolve({
        as_of_date: "2026-02-01",
        currency: "SGD",
        assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000" }],
        liabilities: [],
        equity: [],
        total_assets: "1000",
        total_liabilities: "0",
        total_equity: "1000",
        equation_delta: "0",
        is_balanced: true,
      })
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Cash")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "View source transactions for Cash" }))
    await waitFor(() => expect(screen.getByText("Opening deposit")).toBeInTheDocument())

    // Closing the drawer clears the drill target.
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }))
    await waitFor(() => expect(screen.queryByText("Opening deposit")).toBeNull())
  })

  // AC-reporting.fe-report-surfaces.12
  it("AC16.14.3 toggles tree expansion controls", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [
        { account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: 1000 },
        { account_id: "a-child", name: "Wallet", type: "ASSET", parent_id: "a-root", amount: 100 },
      ],
      liabilities: [],
      equity: [],
      total_assets: 1000,
      total_liabilities: 0,
      total_equity: 1000,
      equation_delta: 0,
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Wallet")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: /Collapse/i }))
    expect(screen.queryByText("Wallet")).not.toBeInTheDocument()
  })

  it("#1486 surfaces the opening-balance warning without presenting source confidence as report assurance", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "-500", provenance: "imported" }],
      liabilities: [],
      equity: [],
      total_assets: "-500",
      total_liabilities: "0",
      total_equity: "0",
      opening_balance_warnings: [
        { type: "missing_opening_balance", message: "Record opening balances to trust this total." },
      ],
      equation_delta: "0",
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument())
    // Warning banner + CTA are shown on the report surface, not just /accounts.
    expect(screen.getByText("Opening balances not recorded")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /set opening balances/i })).toHaveAttribute("href", "/settings?tab=accounts")
    expect(screen.getByText("✓ Balanced")).toBeInTheDocument()
  })

  // AC-reporting.fe-viz-reports.10
  it("renders non-zero CTA adjustment in multicurrency scenario", async () => {
    const vector = {
      ...balanceSheetVector(),
      cta_adjustment: "142.50",
      equation_delta: "0.00",
      is_balanced: true,
    }
    mockedApiFetch.mockResolvedValue(vector)

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument())
    expect(screen.getByText("CTA Adjustment")).toBeInTheDocument()
    expect(screen.getByTestId("equation-detail-cta")).toHaveTextContent("142.50")
    expect(screen.getByText("✓ Balanced")).toBeInTheDocument()
  })

  it("articulates opening equity, net income, and total equity in progressive disclosure", async () => {
    const vector = {
      ...balanceSheetVector(),
      total_assets: "24200.00",
      total_liabilities: "0.00",
      total_equity: "15450.75",
      net_income: "8749.25",
      is_balanced: true,
      currency: "SGD",
    }
    mockedApiFetch.mockResolvedValue(vector)

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument())

    const equationDetail = screen.getByTestId("balance-equation-detail")
    expect(equationDetail.tagName.toLowerCase()).toBe("details")
    expect(screen.getByText("Books in balance")).toBeInTheDocument()

    const equityCard = document.getElementById("equity")!
    expect(within(equityCard).getByText("Opening Equity:")).toBeInTheDocument()
    expect(within(equityCard).getByText("Net Income (P&L):")).toBeInTheDocument()
    expect(within(equityCard).getByText(/15,450\.75/)).toBeInTheDocument()
    expect(within(equityCard).getByText(/8,749\.25/)).toBeInTheDocument()
    expect(within(equityCard).getByText(/24,200\.00/)).toBeInTheDocument()
  })
})
