import "@testing-library/jest-dom/vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import HoldingDetailPage from "@/app/(main)/portfolio/[ticker]/page"
import { apiFetch } from "@/lib/api"
import type { PortfolioHolding } from "@/lib/types"

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
  id: "h2",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "AAPL",
  quantity: "5",
  cost_basis: "700.00",
  market_value: "0.00",
  unrealized_pnl: "0.00",
  unrealized_pnl_percent: "0.00",
  currency: "USD",
  acquisition_date: "2024-06-01",
  disposal_date: "2025-02-01",
  status: "disposed",
  account_name: "IBKR",
  asset_type: "Equity",
  sector: "Technology",
  geography: "US",
}

const mockOtherHolding: PortfolioHolding = {
  id: "h3",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "TSLA",
  quantity: "20",
  cost_basis: "4000.00",
  market_value: "3800.00",
  unrealized_pnl: "-200.00",
  unrealized_pnl_percent: "-5.00",
  currency: "USD",
  acquisition_date: "2025-03-01",
  status: "active",
  account_name: "IBKR",
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
    mockedApiFetch.mockReturnValue(new Promise(() => {}))

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Loading holding details...")).toBeInTheDocument()
  })

  it("renders error state with retry button", async () => {
    mockedApiFetch.mockRejectedValue(new Error("server error"))

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Failed to load holding")).toBeInTheDocument())
    expect(screen.getByText("server error")).toBeInTheDocument()
    expect(screen.getByText("Retry")).toBeInTheDocument()
  })

  it("renders not-found state when no holdings match ticker", async () => {
    mockedApiFetch.mockResolvedValue([mockOtherHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText(/No holdings found for/)).toBeInTheDocument())
    expect(screen.getByText("AAPL")).toBeInTheDocument()
  })

  it("renders KPI cards and active lots table", async () => {
    mockedApiFetch.mockResolvedValue([mockActiveHolding, mockOtherHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getAllByText("Market Value").length).toBeGreaterThanOrEqual(1))
    expect(screen.getAllByText("Cost Basis").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/Unrealized P&L/)).toBeInTheDocument()
    expect(screen.getByText("Quantity")).toBeInTheDocument()
    expect(screen.getByText("FIFO method")).toBeInTheDocument()
    expect(screen.getByText("Active Lots")).toBeInTheDocument()
  })

  it("renders disposed lots table when disposed holdings exist", async () => {
    mockedApiFetch.mockResolvedValue([mockActiveHolding, mockDisposedHolding, mockOtherHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Active Lots")).toBeInTheDocument())
    expect(screen.getByText("Disposed Lots")).toBeInTheDocument()
  })

  it("renders back link to portfolio", async () => {
    mockedApiFetch.mockResolvedValue([mockActiveHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Back to Portfolio")).toBeInTheDocument())
    const link = screen.getByText("Back to Portfolio").closest("a")
    expect(link).toHaveAttribute("href", "/portfolio")
  })

  it("renders sector and geography in page description", async () => {
    mockedApiFetch.mockResolvedValue([mockActiveHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText(/Technology/)).toBeInTheDocument())
    expect(screen.getByText(/US/)).toBeInTheDocument()
  })

  it("fetches all holdings with include_disposed param", async () => {
    mockedApiFetch.mockResolvedValue([mockActiveHolding])

    render(<HoldingDetailPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings?include_disposed=true"))
  })
})
