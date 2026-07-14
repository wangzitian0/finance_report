import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import HoldingDetailPage from "@/app/(main)/portfolio/[ticker]/page"
import { apiFetch } from "@/lib/api"
import type { DividendEvent, PortfolioHolding, RealizedLot } from "@/lib/types"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useParams: () => ({ ticker: "AAPL" }),
  useRouter: () => ({ push: vi.fn() }),
}))

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  TestWrapper.displayName = "HoldingDetailTestWrapper"
  return TestWrapper
}

const mockActiveHolding: PortfolioHolding = {
  id: "h1",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "AAPL",
  quantity: "10",
  cost_basis: "1500.00",
  market_value: "1800.00",
  unrealized_pnl: "300.00",
  unrealized_pnl_percent: "20.00",
  currency: "USD",
  acquisition_date: "2025-01-15",
  status: "active",
  account_name: "IBKR",
  asset_type: "Equity",
  sector: "Technology",
  geography: "US",
  cost_basis_method: "FIFO",
}

const mockDisposedHolding: PortfolioHolding = {
  ...mockActiveHolding,
  id: "h2",
  quantity: "5",
  cost_basis: "700.00",
  market_value: "0.00",
  unrealized_pnl: "0.00",
  unrealized_pnl_percent: "0.00",
  acquisition_date: "2024-06-01",
  disposal_date: "2025-02-01",
  status: "disposed",
}

const mockDividend: DividendEvent = {
  id: "d1",
  ex_date: "2026-02-10",
  pay_date: "2026-02-15",
  amount: "42.50",
  currency: "USD",
  reinvested: false,
}

const mockRealizedLot: RealizedLot = {
  lot_id: "11111111-2222-3333-4444-555555555555",
  acquired_date: "2025-01-15",
  sold_date: "2026-03-01",
  quantity: "5.000000",
  basis: "500.00",
  proceeds: "650.00",
  gain_loss: "150.00",
  holding_period: 410,
  currency: "USD",
}

function mockHoldingDetailApi(options: {
  holdings?: PortfolioHolding[]
  dividends?: DividendEvent[]
  realizedLots?: RealizedLot[]
} = {}) {
  const mockedApiFetch = vi.mocked(apiFetch)
  mockedApiFetch.mockImplementation((path: string, init?: RequestInit) => {
    if (path === "/api/portfolio/holdings?include_disposed=true") {
      const items = options.holdings ?? [mockActiveHolding]
      return Promise.resolve({ items, total: items.length, warnings: [] })
    }
    if (path === "/api/portfolio/AAPL/dividends") {
      return Promise.resolve(options.dividends ?? [mockDividend])
    }
    if (path === "/api/portfolio/AAPL/realized") {
      return Promise.resolve(options.realizedLots ?? [mockRealizedLot])
    }
    if (path === "/api/portfolio/AAPL" && init?.method === "PATCH") {
      return Promise.resolve({ updated_count: 1, cost_basis_method: "LIFO" })
    }
    return Promise.reject(new Error(`unhandled path ${path}`))
  })
}

describe("HoldingDetailPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders loading state", () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/portfolio/holdings?include_disposed=true") return new Promise(() => {})
      return Promise.resolve([])
    })

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Loading holding details...")).toBeInTheDocument()
  })

  it("renders error state with retry button", async () => {
    mockedApiFetch.mockRejectedValue(new Error("server error"))

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Failed to load holding")).toBeInTheDocument())
    expect(screen.getByText("server error")).toBeInTheDocument()
    const callCountBeforeRetry = mockedApiFetch.mock.calls.length
    fireEvent.click(screen.getByText("Retry"))
    await waitFor(() => expect(mockedApiFetch.mock.calls.length).toBeGreaterThan(callCountBeforeRetry))
  })

  it("renders not-found state when no holdings match ticker", async () => {
    mockHoldingDetailApi({ holdings: [{ ...mockActiveHolding, id: "h3", asset_identifier: "TSLA" }] })

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText(/No holdings found for/)).toBeInTheDocument())
    expect(screen.getByText("AAPL")).toBeInTheDocument()
  })

  // AC-portfolio.fe-assets2.20
  it("AC17.7.1 renders Overview, Dividends, and Realized P&L tabs", async () => {
    mockHoldingDetailApi()

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument())
    expect(screen.getByRole("tab", { name: "Dividends" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Realized P&L" })).toBeInTheDocument()
  })

  it("renders KPI cards and active/disposed lots in the overview tab", async () => {
    mockHoldingDetailApi({ holdings: [{ ...mockActiveHolding, quantity: "10.123456789" }, mockDisposedHolding] })

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getAllByText("Market Value").length).toBeGreaterThanOrEqual(1))
    expect(screen.getAllByText("Cost Basis").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/Unrealized P&L/)).toBeInTheDocument()
    expect(screen.getByText("Active Lots")).toBeInTheDocument()
    expect(screen.getByText("Disposed Lots")).toBeInTheDocument()
    expect(screen.getByText("FIFO method")).toBeInTheDocument()
    expect(screen.getAllByText("10.123456789").length).toBeGreaterThanOrEqual(1)
  })

  // AC-portfolio.fe-assets2.21
  it("AC17.7.2/AC17.7.6 switches to Dividends tab and renders dividend row labels", async () => {
    mockHoldingDetailApi()

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    fireEvent.click(await screen.findByRole("tab", { name: "Dividends" }))

    expect(screen.getByText("Dividend Events")).toBeInTheDocument()
    expect(screen.getByText("Ex Date")).toBeInTheDocument()
    expect(screen.getByText("Pay Date")).toBeInTheDocument()
    expect(screen.getByText("Amount")).toBeInTheDocument()
    expect(screen.getByText("Currency")).toBeInTheDocument()
    expect(screen.getByText("Reinvested")).toBeInTheDocument()
    expect(screen.getByText("$42.50")).toBeInTheDocument()
  })

  // AC-portfolio.fe-assets2.22
  it("AC17.7.3 persists cost-basis method and refetches realized P&L", async () => {
    mockHoldingDetailApi()

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByLabelText("Cost basis method")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("Cost basis method"), { target: { value: "LIFO" } })

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/portfolio/AAPL",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ cost_basis_method: "LIFO" }),
        }),
      ),
    )
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/AAPL/realized")
  })

  // AC-portfolio.fe-assets2.23
  it("AC17.7.4 renders lot-level realized P&L table", async () => {
    mockHoldingDetailApi()

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    fireEvent.click(await screen.findByRole("tab", { name: "Realized P&L" }))

    const table = screen.getByText("Realized P&L Lots").closest(".card")
    expect(table).not.toBeNull()
    expect(within(table as HTMLElement).getByText("Lot")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("Acquired")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("Sold")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("Basis")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("Proceeds")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("Gain/Loss")).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText("$150.00")).toBeInTheDocument()
  })

  it("fetches all holdings with include_disposed param and renders back link", async () => {
    mockHoldingDetailApi()

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings?include_disposed=true"))
    const link = (await screen.findByText("Back to Portfolio")).closest("a")
    expect(link).toHaveAttribute("href", "/portfolio")
  })
})
