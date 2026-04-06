import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import PricesPage from "@/app/(main)/portfolio/prices/page"
import { apiFetch } from "@/lib/api"
import type { PortfolioHolding, PriceUpdateResponse } from "@/lib/types"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
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
  TestWrapper.displayName = "PricesTestWrapper"
  return TestWrapper
}

const mockHoldings: PortfolioHolding[] = [
  {
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
  },
  {
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
    status: "active",
    account_name: "IBKR",
  },
]

describe("PricesPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders page header and back link", async () => {
    mockedApiFetch.mockResolvedValue(mockHoldings)

    render(<PricesPage />, { wrapper: createWrapper() })

    expect(screen.getByText("Update Market Prices")).toBeInTheDocument()
    expect(screen.getByText(/Manually update market prices/)).toBeInTheDocument()

    const backLink = screen.getByText("Back to Portfolio").closest("a")
    expect(backLink).toHaveAttribute("href", "/portfolio")
  })

  it("renders price update form with known tickers from holdings", async () => {
    mockedApiFetch.mockResolvedValue(mockHoldings)

    render(<PricesPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Batch Price Update")).toBeInTheDocument())
    expect(screen.getByText("Update Prices")).toBeInTheDocument()
    expect(screen.getByText("Add Row")).toBeInTheDocument()
  })

  it("renders ticker select with known tickers", async () => {
    mockedApiFetch.mockResolvedValue(mockHoldings)

    render(<PricesPage />, { wrapper: createWrapper() })

    await waitFor(() => {
      const options = screen.getAllByRole("option")
      const optionTexts = options.map((o) => o.textContent)
      expect(optionTexts).toContain("AAPL")
      expect(optionTexts).toContain("TSLA")
    })
  })

  it("adds and removes rows", async () => {
    mockedApiFetch.mockResolvedValue(mockHoldings)
    render(<PricesPage />, { wrapper: createWrapper() })
    await waitFor(() => {
      const options = screen.getAllByRole("option")
      expect(options.map((o) => o.textContent)).toContain("AAPL")
    })
    fireEvent.click(screen.getByText("Add Row"))
    const selects = screen.getAllByRole("combobox")
    expect(selects.length).toBe(2)
    const removeButtons = screen.getAllByLabelText("Remove row")
    fireEvent.click(removeButtons[1])
    expect(screen.getAllByRole("combobox").length).toBe(1)
  })

  it("submits price update and shows success toast", async () => {
    const mockResponse: PriceUpdateResponse = {
      updated_count: 1,
      results: [
        {
          success: true,
          message: "Updated",
          asset_identifier: "AAPL",
          price_date: "2026-04-06",
          price: "180.00",
          currency: "USD",
          source: "manual",
        },
      ],
    }

    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/portfolio/prices/update" && options?.method === "POST") {
        return Promise.resolve(mockResponse)
      }
      return Promise.resolve(mockHoldings)
    })

    render(<PricesPage />, { wrapper: createWrapper() })

    await waitFor(() => {
      const options = screen.getAllByRole("option")
      expect(options.map((o) => o.textContent)).toContain("AAPL")
    })

    const select = screen.getAllByRole("combobox")[0]
    fireEvent.change(select, { target: { value: "AAPL" } })

    const priceInput = screen.getByPlaceholderText("0.00")
    fireEvent.change(priceInput, { target: { value: "180.00" } })

    const form = screen.getByText("Update Prices").closest("form") as HTMLFormElement
    fireEvent.submit(form)

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/portfolio/prices/update",
        expect.objectContaining({ method: "POST" })
      )
    })

    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith("Updated 1 price(s)", "success")
    })
  })

  it("shows error toast when submitting empty form", async () => {
    mockedApiFetch.mockResolvedValue(mockHoldings)
    render(<PricesPage />, { wrapper: createWrapper() })

    await waitFor(() => {
      const options = screen.getAllByRole("option")
      expect(options.map((o) => o.textContent)).toContain("AAPL")
    })

    const form = screen.getByText("Update Prices").closest("form") as HTMLFormElement
    fireEvent.submit(form)
    expect(showToastMock).toHaveBeenCalledWith("Add at least one price update", "error")
  })
})
