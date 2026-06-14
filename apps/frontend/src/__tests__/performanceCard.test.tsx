import "@testing-library/jest-dom/vitest"
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PerformanceCard } from "@/components/portfolio/PerformanceCard"
import type { InvestmentPerformanceReportSchedule } from "@/lib/types"

const baseSchedule: InvestmentPerformanceReportSchedule = {
  period_start: "2026-01-01",
  period_end: "2026-03-31",
  as_of_date: "2026-04-01",
  currency: "SGD",
  xirr: "8.25",
  time_weighted_return: "5.00",
  money_weighted_return: "4.00",
  dividend_yield: "1.50",
  realized_pnl: "1200.00",
  unrealized_pnl: "300.00",
  dividend_income: "88.00",
  holdings: [
    {
      asset_identifier: "AAPL",
      quantity: "10",
      cost_basis: "1000.00",
      market_value: "1200.00",
      unrealized_pnl: "200.00",
      realized_pnl: "0.00",
      dividend_income: "0.00",
      currency: "SGD",
    },
    {
      asset_identifier: "MSFT",
      quantity: "5",
      cost_basis: "2000.00",
      market_value: "2100.00",
      unrealized_pnl: "100.00",
      realized_pnl: "0.00",
      dividend_income: "0.00",
      currency: "SGD",
    },
  ],
  allocation: [],
  data_freshness: {
    latest_price_date: "2026-04-01",
    market_data_provider: "IBKR",
    stale: false,
    stale_holdings: [],
    manual_override_basis: null,
  },
  source_links: [],
  notes: [],
}

describe("PerformanceCard", () => {
  it("renders loading spinner", () => {
    render(<PerformanceCard isLoading />)
    expect(screen.getByText("Performance")).toBeInTheDocument()
    expect(document.querySelector(".animate-spin")).toBeTruthy()
  })

  it("renders error state", () => {
    render(<PerformanceCard error={new Error("network error")} />)
    expect(screen.getByText("Unable to load performance metrics")).toBeInTheDocument()
  })

  it("AC17.14.4 leads with unrealized gain/loss, return on cost, and price freshness", () => {
    render(<PerformanceCard schedule={baseSchedule} />)

    expect(screen.getByText("Market-Value Performance")).toBeInTheDocument()
    expect(screen.getByText("Unrealized gain/loss")).toBeInTheDocument()
    expect(screen.getByText("Return on cost")).toBeInTheDocument()
    // 300 unrealized / 3000 cost basis = +10.00%
    const ret = screen.getByText("+10.00%")
    expect(ret).toHaveClass("text-[var(--success)]")
    expect(screen.getByText("Prices current")).toBeInTheDocument()
    expect(screen.getByText("as of 2026-04-01")).toBeInTheDocument()
  })

  it("AC17.14.4 does not present TWR/IRR/MWR as the asset-dashboard answer", () => {
    render(<PerformanceCard schedule={baseSchedule} />)
    expect(screen.queryByText("XIRR")).not.toBeInTheDocument()
    expect(screen.queryByText("TWR")).not.toBeInTheDocument()
    expect(screen.queryByText("MWR")).not.toBeInTheDocument()
  })

  it("AC17.14.4 flags stale prices", () => {
    render(
      <PerformanceCard
        schedule={{
          ...baseSchedule,
          data_freshness: { ...baseSchedule.data_freshness, stale: true, stale_holdings: ["AAPL"] },
        }}
      />,
    )
    const flag = screen.getByText("Prices stale")
    expect(flag).toHaveClass("text-[var(--error)]")
  })

  it("AC17.14.4 colors a negative return as a loss", () => {
    render(
      <PerformanceCard
        schedule={{
          ...baseSchedule,
          unrealized_pnl: "-300.00",
          holdings: [{ ...baseSchedule.holdings[0], cost_basis: "3000.00", unrealized_pnl: "-300.00" }],
        }}
      />,
    )
    // -300 / 3000 = -10.00%
    const ret = screen.getByText("-10.00%")
    expect(ret).toHaveClass("text-[var(--error)]")
  })

  it("AC17.14.4 shows N/A return when cost basis is zero", () => {
    render(
      <PerformanceCard
        schedule={{ ...baseSchedule, unrealized_pnl: "0.00", holdings: [] }}
      />,
    )
    expect(screen.getByText("N/A")).toBeInTheDocument()
  })
})
