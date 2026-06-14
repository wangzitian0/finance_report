import { describe, expect, it } from "vitest"

import { computeMarketValuePerformance } from "@/lib/portfolioPerformance"
import type { InvestmentPerformanceReportSchedule } from "@/lib/types"

const base: InvestmentPerformanceReportSchedule = {
  period_start: "2026-01-01",
  period_end: "2026-03-31",
  as_of_date: "2026-04-01",
  currency: "SGD",
  xirr: "0.00",
  time_weighted_return: "0.00",
  money_weighted_return: "0.00",
  dividend_yield: "0.00",
  realized_pnl: "0.00",
  unrealized_pnl: "300.00",
  dividend_income: "0.00",
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

describe("computeMarketValuePerformance", () => {
  it("derives totals and return on cost from holdings", () => {
    const result = computeMarketValuePerformance(base)
    expect(result.totalCostBasis).toBe("3000.00")
    expect(result.totalMarketValue).toBe("3300.00")
    expect(result.unrealizedPnl).toBe("300.00")
    expect(result.returnOnCostPercent).toBe("10.00")
  })

  it("returns null return on cost when cost basis is zero", () => {
    const result = computeMarketValuePerformance({ ...base, unrealized_pnl: "0.00", holdings: [] })
    expect(result.totalCostBasis).toBe("0.00")
    expect(result.returnOnCostPercent).toBeNull()
  })

  it("tolerates a partial schedule missing the holdings array", () => {
    const partial = { ...base, holdings: undefined } as unknown as InvestmentPerformanceReportSchedule
    const result = computeMarketValuePerformance(partial)
    expect(result.totalCostBasis).toBe("0.00")
    expect(result.returnOnCostPercent).toBeNull()
  })
})
