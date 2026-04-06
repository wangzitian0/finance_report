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
  id: "h2",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "TSLA",
  quantity: "5",
  cost_basis: "1000.00",
  market_value: "900.00",
  unrealized_pnl: "-100.00",
  unrealized_pnl_percent: "-10.00",
  currency: "USD",
  acquisition_date: "2025-03-01",
  disposal_date: "2025-11-01",
  status: "disposed",
  account_name: "IBKR",
  asset_type: "Equity",
  sector: "Automotive",
  geography: "US",
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
    mockedApiFetch.mockResolvedValue([mockHolding])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Portfolio")).toBeInTheDocument()
    expect(screen.getByText(/Track your investment holdings/)).toBeInTheDocument()
    expect(screen.getByText("Update Prices")).toBeInTheDocument()
    expect(screen.getByTestId("performance-card")).toBeInTheDocument()
    expect(screen.getByTestId("allocation-chart-sector")).toBeInTheDocument()
    expect(screen.getByTestId("allocation-chart-geography")).toBeInTheDocument()
  })

  it("renders loading state while fetching holdings", () => {
    mockedApiFetch.mockReturnValue(new Promise(() => {}))

    render(<PortfolioPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Loading holdings...")).toBeInTheDocument()
  })

  it("renders error state with retry button", async () => {
    mockedApiFetch.mockRejectedValue(new Error("network error"))

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Failed to load holdings")).toBeInTheDocument())
    expect(screen.getByText("network error")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Retry loading holdings" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2))
  })

  it("renders empty state when no holdings", async () => {
    mockedApiFetch.mockResolvedValue([])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("No holdings found")).toBeInTheDocument())
    expect(screen.getByText(/Upload brokerage statements/)).toBeInTheDocument()
  })

  it("renders holdings table when data is loaded", async () => {
    mockedApiFetch.mockResolvedValue([mockHolding])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument())
    expect(screen.getByText("IBKR")).toBeInTheDocument()
  })

  it("toggles show disposed checkbox and refetches with include_disposed", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("include_disposed=true")) {
        return Promise.resolve([mockHolding, mockHolding2])
      }
      return Promise.resolve([mockHolding])
    })

    render(<PortfolioPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument())

    const checkbox = screen.getByRole("checkbox")
    fireEvent.click(checkbox)

    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument())
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings?include_disposed=true")
  })

  it("has a link to the prices page", async () => {
    mockedApiFetch.mockResolvedValue([])

    render(<PortfolioPage />, { wrapper: createWrapper() })

    const link = screen.getByText("Update Prices").closest("a")
    expect(link).toHaveAttribute("href", "/portfolio/prices")
  })
})
