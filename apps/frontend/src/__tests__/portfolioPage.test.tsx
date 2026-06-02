import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import PortfolioPage from "@/app/(main)/portfolio/page"
import { apiFetch } from "@/lib/api"
import type { PortfolioHolding } from "@/lib/types"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("@/components/portfolio/PerformanceCard", () => ({
  PerformanceCard: () => <div data-testid="performance-card">PerformanceCard</div>,
}))

vi.mock("@/components/portfolio/AllocationChart", () => ({
  AllocationChart: ({ type, title }: { type: string; title: string }) => (
    <div data-testid={`allocation-chart-${type}`}>{title}</div>
  ),
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
  TestWrapper.displayName = "PortfolioTestWrapper"
  return TestWrapper
}

const mockHolding: PortfolioHolding = {
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
}

const mockHolding2: PortfolioHolding = {
  ...mockHolding,
  id: "h2",
  asset_identifier: "TSLA",
  quantity: "5",
  cost_basis: "1000.00",
  market_value: "900.00",
  unrealized_pnl: "-100.00",
  unrealized_pnl_percent: "-10.00",
  disposal_date: "2025-11-01",
  status: "disposed",
  sector: "Automotive",
}

function mockPortfolioApi(holdings: PortfolioHolding[] = [mockHolding]) {
  const mockedApiFetch = vi.mocked(apiFetch)
  mockedApiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/portfolio/summary")) {
      return Promise.resolve({
        total_market_value: "1800.00",
        total_cost_basis: "1500.00",
        total_unrealized_pnl: "300.00",
        total_unrealized_pnl_percent: "20.00",
        total_realized_pnl: "149.00",
        total_realized_pnl_percent: "9.93",
        net_pnl: "449.00",
        net_pnl_percent: "29.93",
        holdings_count: holdings.length,
        active_positions_count: holdings.filter((h) => h.status === "active").length,
        disposed_positions_count: holdings.filter((h) => h.status === "disposed").length,
        currency: "SGD",
        realized_pnl_ytd: "149.00",
        dividend_income_ytd: "42.50",
      })
    }
    if (path.startsWith("/api/portfolio/performance/report-schedule")) {
      return Promise.resolve({
        period_start: "2026-01-01",
        period_end: "2026-12-31",
        as_of_date: "2026-12-31",
        currency: "USD",
        xirr: "12.50",
        time_weighted_return: "8.30",
        money_weighted_return: "10.10",
        realized_pnl: "149.00",
        unrealized_pnl: "300.00",
        dividend_income: "42.50",
        dividend_yield: "2.36",
        holdings: [
          {
            asset_identifier: "AAPL",
            quantity: "10.000000",
            cost_basis: "1500.00",
            market_value: "1800.00",
            unrealized_pnl: "300.00",
            realized_pnl: "149.00",
            dividend_income: "42.50",
            currency: "SGD",
          },
        ],
        allocation: [{ dimension: "sector", category: "Technology", value: "1800.00", percentage: "100.00", count: 1 }],
        data_freshness: {
          latest_price_date: "2026-12-31",
          market_data_provider: "Test Broker",
          stale: false,
          stale_holdings: [],
          manual_override_basis: null,
        },
        source_links: ["brokerage_statement:aapl"],
        notes: ["Cost basis uses FIFO where available."],
      })
    }
    if (path.startsWith("/api/portfolio/holdings")) {
      if (path.includes("include_disposed=true")) return Promise.resolve([mockHolding, mockHolding2])
      return Promise.resolve(holdings)
    }
    return Promise.reject(new Error(`unhandled path ${path}`))
  })
}

describe("PortfolioPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders page header and child components", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Portfolio")).toBeInTheDocument()
    expect(screen.getByText(/Track your investment holdings/)).toBeInTheDocument()
    expect(screen.getByText("Update Prices")).toBeInTheDocument()
    expect(screen.getByTestId("performance-card")).toBeInTheDocument()
    expect(screen.getByTestId("allocation-chart-sector")).toBeInTheDocument()
    expect(screen.getByTestId("allocation-chart-geography")).toBeInTheDocument()
  })

  it("renders loading state while fetching holdings", () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/portfolio/summary")) return Promise.resolve({})
      return new Promise(() => {})
    })

    render(<PortfolioPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Loading holdings...")).toBeInTheDocument()
  })

  it("renders error state with retry button", async () => {
    mockedApiFetch.mockRejectedValue(new Error("network error"))

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Failed to load holdings")).toBeInTheDocument())
    expect(screen.getByText("network error")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Retry loading holdings" }))
    await waitFor(() => expect(mockedApiFetch.mock.calls.length).toBeGreaterThan(2))
  })

  it("renders empty state when no holdings", async () => {
    mockPortfolioApi([])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("No holdings found")).toBeInTheDocument())
    expect(screen.getByText(/Upload brokerage statements/)).toBeInTheDocument()
  })

  it("renders holdings table when data is loaded", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument())
    expect(screen.getByText("IBKR")).toBeInTheDocument()
  })

  it("toggles show disposed checkbox and refetches with include_disposed", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("checkbox"))

    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument())
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings?include_disposed=true")
  })

  it("AC17.9.3 passes selected as-of date to holdings API", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Portfolio as-of date"), {
      target: { value: "2025-01-31" },
    })

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings?as_of_date=2025-01-31"),
    )

    fireEvent.click(screen.getByLabelText("Clear portfolio as-of date"))

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings"))
  })

  it("has a link to the prices page", async () => {
    mockPortfolioApi([])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    const link = screen.getByText("Update Prices").closest("a")
    expect(link).toHaveAttribute("href", "/portfolio/prices")
  })

  it("AC17.8.4 shows total portfolio value banner when active holdings are loaded", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByTestId("total-portfolio-value")).toBeInTheDocument())
    expect(screen.getByText("Total Portfolio Value")).toBeInTheDocument()
    expect(screen.getByTestId("total-portfolio-value")).toHaveTextContent("1,800")
  })

  it("AC17.7.5 renders realized P&L YTD and dividend income YTD from portfolio summary", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Realized P&L YTD")).toBeInTheDocument())
    expect(screen.getByText("Dividend Income YTD")).toBeInTheDocument()
    expect(screen.getAllByText("$149.00").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("$42.50").length).toBeGreaterThanOrEqual(1)
  })

  it("AC5.8.1 renders investment performance report schedule from the schedule API", async () => {
    mockPortfolioApi()

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("investment_performance")).toBeInTheDocument())
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/performance/report-schedule")
    expect(screen.getByText(/Report section/)).toBeInTheDocument()
    expect(screen.getByText("Source Links")).toBeInTheDocument()
    expect(screen.getByText("brokerage_statement:aapl")).toBeInTheDocument()
    expect(screen.getByText("Cost basis uses FIFO where available.")).toBeInTheDocument()
  })

  it("AC17.8.4 does not show total portfolio value banner when no active holdings", async () => {
    mockPortfolioApi([])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("No holdings found")).toBeInTheDocument())
    expect(screen.queryByTestId("total-portfolio-value")).not.toBeInTheDocument()
  })
})
