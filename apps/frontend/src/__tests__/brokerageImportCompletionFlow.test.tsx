import "@testing-library/jest-dom/vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { useEffect, useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import PortfolioPage from "@/app/(main)/portfolio/page"
import StatementDetailPage from "@/app/(main)/statements/[id]/page"
import { ToastProvider } from "@/components/ui/Toast"
import { apiFetch } from "@/lib/api"
import type { PortfolioHolding } from "@/lib/types"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useParams: vi.fn(() => {
    const statementMatch = window.location.pathname.match(/^\/statements\/([^/]+)/)
    return statementMatch ? { id: statementMatch[1] } : {}
  }),
  useSearchParams: vi.fn(() => new URLSearchParams(window.location.search)),
}))

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    onClick,
    ...rest
  }: {
    href: string
    children: React.ReactNode
    onClick?: React.MouseEventHandler<HTMLAnchorElement>
    [key: string]: unknown
  }) => (
    <a
      href={href}
      onClick={(event) => {
        onClick?.(event)
        if (!event.defaultPrevented && href.startsWith("/")) {
          event.preventDefault()
          window.history.pushState({}, "", href)
          window.dispatchEvent(new Event("popstate"))
        }
      }}
      {...rest}
    >
      {children}
    </a>
  ),
}))

vi.mock("@/components/portfolio/PerformanceCard", () => ({
  PerformanceCard: () => <div data-testid="performance-card">PerformanceCard</div>,
}))

vi.mock("@/components/portfolio/AllocationChart", () => ({
  AllocationChart: ({ type, title }: { type: string; title: string }) => (
    <div data-testid={`allocation-chart-${type}`}>{title}</div>
  ),
}))

const parsedBrokerageStatement = {
  id: "s1",
  original_filename: "moomoo-2026-01.pdf",
  institution: "Moomoo",
  currency: "USD",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  opening_balance: null,
  closing_balance: null,
  status: "parsed",
  parsing_progress: 100,
  transactions: [],
}

const importedHolding: PortfolioHolding = {
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
  acquisition_date: "2026-01-31",
  status: "active",
  account_name: "Moomoo",
  asset_type: "Equity",
  sector: "Technology",
  geography: "US",
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  )
  TestWrapper.displayName = "BrokerageImportFlowWrapper"
  return TestWrapper
}

function RouteHarness() {
  const [path, setPath] = useState(window.location.pathname)

  useEffect(() => {
    const onRouteChange = () => setPath(window.location.pathname)
    window.addEventListener("popstate", onRouteChange)
    return () => window.removeEventListener("popstate", onRouteChange)
  }, [])

  if (path === "/portfolio") {
    return <PortfolioPage />
  }
  return <StatementDetailPage />
}

describe("Brokerage import completion route flow", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    window.history.pushState({}, "", "/statements/s1")
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/s1") {
        return Promise.resolve(parsedBrokerageStatement as any)
      }
      if (path === "/api/statements/s1/brokerage/import") {
        return Promise.resolve({
          broker: "Moomoo",
          parsed_positions: 1,
          created_atomic_positions: 1,
          existing_atomic_positions: 0,
          reconcile_created: 1,
          reconcile_updated: 0,
          reconcile_disposed: 0,
          skipped: 0,
        } as any)
      }
      if (path.startsWith("/api/portfolio/summary")) {
        return Promise.resolve({
          total_market_value: "1800.00",
          total_cost_basis: "1500.00",
          total_unrealized_pnl: "300.00",
          total_unrealized_pnl_percent: "20.00",
          total_realized_pnl: "0.00",
          total_realized_pnl_percent: "0.00",
          net_pnl: "300.00",
          net_pnl_percent: "20.00",
          holdings_count: 1,
          active_positions_count: 1,
          disposed_positions_count: 0,
          currency: "USD",
          realized_pnl_ytd: "0.00",
          dividend_income_ytd: "0.00",
        } as any)
      }
      if (path.startsWith("/api/portfolio/holdings")) {
        return Promise.resolve([importedHolding] as any)
      }
      return Promise.reject(new Error(`Unhandled API path: ${path}`))
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation", async () => {
    const user = userEvent.setup()

    render(<RouteHarness />, { wrapper: createWrapper() })

    const importButton = await screen.findByRole("button", {
      name: /import brokerage positions to portfolio/i,
    })
    await user.click(importButton)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/brokerage/import", {
        method: "POST",
      }),
    )
    expect(await screen.findByTestId("import-result-banner")).toHaveTextContent(
      "Brokerage positions imported successfully",
    )

    await user.click(screen.getByRole("link", { name: /view portfolio after import/i }))

    await waitFor(() => expect(window.location.pathname).toBe("/portfolio"))
    expect(await screen.findByText("Total Portfolio Value")).toBeInTheDocument()
    expect(screen.getByTestId("total-portfolio-value")).toHaveTextContent("$1,800.00")
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings")
  })
})
