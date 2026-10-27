import "@testing-library/jest-dom/vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { HoldingsTable } from "@/components/portfolio/Holdings"
import UnmatchedBoard from "@/components/reconciliation/UnmatchedBoard"
import { BalanceSheetPanel } from "@/components/reports/StatementPanels"
import { apiOperation } from "@/lib/api-client"
import type { PortfolioHolding } from "@/lib/types"

function createTestQueryWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  TestWrapper.displayName = "TestQueryWrapper"
  return TestWrapper
}

const navigationState = vi.hoisted(() => ({ searchParams: new URLSearchParams() }))

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigationState.searchParams,
}))

vi.mock("@/lib/api-client", () => ({
  API_URL: "http://localhost:8000",
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}))

describe("Issue #2762 responsive overflow and negative currency wrapping", () => {
  const mockedApiOperation = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiOperation.mockReset()
    navigationState.searchParams = new URLSearchParams()
  })

  it("renders BalanceSheetPanel negative currency amounts with whitespace-nowrap inside a shrink-0 wrapper and min-w-0 section cards", async () => {
    mockedApiOperation.mockImplementation(((operationId: string) => {
      if (operationId === "balance_sheet_reports_balance_sheet_get") {
        return Promise.resolve({
          as_of_date: "2026-02-01",
          currency: "SGD",
          assets: [
            {
              account_id: "asset-neg",
              name: "Margin Cash Account With Very Long Label",
              type: "ASSET",
              parent_id: null,
              amount: "-1250.00",
              provenance: "imported",
            },
          ],
          liabilities: [
            {
              account_id: "liab-1",
              name: "Credit Card Payable",
              type: "LIABILITY",
              parent_id: null,
              amount: "450.00",
              provenance: "imported",
            },
          ],
          equity: [
            {
              account_id: "eq-1",
              name: "Retained Earnings",
              type: "EQUITY",
              parent_id: null,
              amount: "-1700.00",
              provenance: "derived",
            },
          ],
          total_assets: "-1250.00",
          total_liabilities: "450.00",
          total_equity: "-1700.00",
          net_income: "-200.00",
          unrealized_fx_gain_loss: "-15.00",
          cta_adjustment: "0.00",
          net_worth_adjustment_gain_loss: "-35.00",
          equation_delta: "0.00",
          is_balanced: true,
        })
      }
      return Promise.resolve({ currency: "SGD", granularity: "monthly", points: [] })
    }) as any)

    render(
      <BalanceSheetPanel
        filters={{
          tab: "balance-sheet",
          preset: "1M",
          startDate: "2026-01-01",
          endDate: "2026-02-01",
          isCurrent: false,
          currency: "SGD",
          includeRestricted: true,
          openingDate: "2025-12-31",
          isDefaultPeriod: false,
          opensAtCoverageStart: false,
          coverageLimitingAccounts: [],
          latestStatementEnd: null,
          previousEnd: "2025-12-31",
          nextEnd: "2026-02-28",
          dimensionQuery: "period=1M&end=2026-02-01",
          ready: true,
        }}
      />,
      { wrapper: createTestQueryWrapper() },
    )

    const amountBtn = await screen.findByRole("button", {
      name: "View source transactions for Margin Cash Account With Very Long Label",
    })
    expect(amountBtn).toHaveTextContent("-SGD 1,250.00")
    expect(amountBtn).toHaveClass("whitespace-nowrap", "tabular-nums")
    expect(amountBtn.parentElement).toHaveClass("shrink-0")

    const labelBtn = screen.getByRole("button", { name: "Margin Cash Account With Very Long Label" })
    expect(labelBtn.parentElement).toHaveClass("min-w-0", "flex-1")

    const assetsCard = document.getElementById("assets")!
    const liabilitiesCard = document.getElementById("liabilities")!
    const equityCard = document.getElementById("equity")!
    expect(assetsCard).toHaveClass("min-w-0", "overflow-hidden")
    expect(liabilitiesCard).toHaveClass("min-w-0", "overflow-hidden")
    expect(equityCard).toHaveClass("min-w-0", "overflow-hidden")

    const equationDetail = screen.getByTestId("balance-equation-detail")
    expect(equationDetail).toHaveClass("min-w-0", "overflow-hidden")

    const equityTotalValue = within(equityCard).getByText("Total:").nextElementSibling
    expect(equityTotalValue).toHaveClass("whitespace-nowrap", "shrink-0")
  })

  it("enforces min-w-0 and responsive column containment on HoldingsTable", () => {
    const holding: PortfolioHolding = {
      id: "h-2762",
      user_id: "u1",
      account_id: "acc1",
      asset_identifier: "VWRA",
      quantity: "42.5",
      cost_basis: "5000.00",
      market_value: "5450.00",
      unrealized_pnl: "450.00",
      unrealized_pnl_percent: "9.00",
      currency: "SGD",
      native_cost_basis: "5000.00",
      native_currency: "USD",
      reporting_cost_basis: "5000.00",
      reporting_currency: "SGD",
      acquisition_date: "2025-06-15",
      status: "active",
      account_name: "Interactive Brokers Singapore",
    }

    const { container } = render(<HoldingsTable holdings={[holding]} />)

    const card = container.querySelector(".card")
    expect(card).toHaveClass("overflow-hidden", "min-w-0")

    const scrollContainer = card?.querySelector(".overflow-x-auto")
    expect(scrollContainer).toHaveClass("max-w-full")

    // Secondary columns collapse on small mobile viewports while primary columns stay visible
    const costBasisHeader = screen.getByRole("columnheader", { name: "Cost Basis" })
    const pnlPercentHeader = screen.getByRole("columnheader", { name: "P&L %" })
    const statusHeader = screen.getByRole("columnheader", { name: "Status" })
    expect(costBasisHeader).toHaveClass("hidden", "md:table-cell")
    expect(pnlPercentHeader).toHaveClass("hidden", "md:table-cell")
    expect(statusHeader).toHaveClass("hidden", "lg:table-cell")

    const marketValueCell = screen.getByText("SGD 5,450.00")
    expect(marketValueCell).toHaveClass("whitespace-nowrap", "tabular-nums")
  })

  it("enforces min-w-0 and whitespace-nowrap shrink-0 amounts on UnmatchedBoard", async () => {
    mockedApiOperation
      .mockResolvedValueOnce({
        items: [
          {
            id: "txn-2762",
            statement_id: "s1",
            txn_date: "2026-02-01",
            description: "LONG MERCHANT DESCRIPTION WITHOUT SPACES OR BREAKS FOR MOBILE",
            amount: "-980.50",
            currency: "SGD",
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({ items: [], total: 0 })

    const { container } = render(<UnmatchedBoard />)

    await waitFor(() => {
      expect(screen.getAllByText("-SGD 980.50")).toHaveLength(2)
    })

    const cards = container.querySelectorAll(".card")
    expect(cards.length).toBe(2)
    cards.forEach((card) => {
      expect(card).toHaveClass("min-w-0", "overflow-hidden")
    })

    const amounts = screen.getAllByText("-SGD 980.50")
    expect(amounts[0]).toHaveClass("whitespace-nowrap", "tabular-nums")
    expect(amounts[0].parentElement).toHaveClass("shrink-0")
    expect(amounts[1]).toHaveClass("whitespace-nowrap", "tabular-nums")
  })
})
