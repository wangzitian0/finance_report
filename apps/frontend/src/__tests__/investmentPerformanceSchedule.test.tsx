import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { InvestmentPerformanceSchedule } from "@/components/portfolio/InvestmentPerformanceSchedule"

const schedule = {
  period_start: "2026-01-01",
  period_end: "2026-03-31",
  as_of_date: "2026-04-01",
  currency: "SGD",
  xirr: "8.25",
  time_weighted_return: null,
  money_weighted_return: "not-a-number",
  dividend_yield: "-1.50",
  realized_pnl: "1200.00",
  unrealized_pnl: "-300.00",
  dividend_income: "88.00",
  data_freshness: {
    latest_price_date: null,
    market_data_provider: null,
    stale: true,
    stale_holdings: ["AAPL", "0700.HK"],
    manual_override_basis: "manual broker statement",
  },
  source_links: [],
  notes: [],
}

describe("InvestmentPerformanceSchedule", () => {
  it("AC8.13.92 renders loading and unavailable states", () => {
    const { rerender } = render(<InvestmentPerformanceSchedule isLoading />)

    expect(screen.getByText("Investment Performance Report Schedule")).toBeInTheDocument()
    expect(document.querySelector("[aria-busy='true']")).toBeInTheDocument()

    rerender(<InvestmentPerformanceSchedule error={new Error("down")} />)
    expect(screen.getByText("Unable to load investment performance schedule")).toBeInTheDocument()
  })

  it("AC8.13.92 renders stale data, missing metrics, and empty source/notes branches", () => {
    render(<InvestmentPerformanceSchedule schedule={schedule as never} />)

    expect(screen.getByText("+8.25%")).toHaveClass("text-[var(--success)]")
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("-1.50%")).toHaveClass("text-[var(--error)]")
    expect(screen.getByText("Status: Stale")).toBeInTheDocument()
    expect(screen.getByText("Stale holdings: AAPL, 0700.HK")).toBeInTheDocument()
    expect(screen.getByText("Manual override: manual broker statement")).toBeInTheDocument()
    expect(screen.getByText("No source links available")).toBeInTheDocument()
    expect(screen.queryByText("Notes")).not.toBeInTheDocument()
  })

  it("AC8.13.92 renders neutral metrics and missing stale holdings defensively", () => {
    render(
      <InvestmentPerformanceSchedule
        schedule={{
          ...schedule,
          xirr: "0.00",
          money_weighted_return: "0.00",
          data_freshness: {
            latest_price_date: "2026-04-01",
            market_data_provider: "manual",
            stale: false,
            manual_override_basis: null,
          },
          source_links: ["statement:aapl"],
          notes: ["Reviewed manually"],
        } as never}
      />,
    )

    expect(screen.getAllByText("0.00%").length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("Status: Current")).toBeInTheDocument()
    expect(screen.queryByText(/Stale holdings:/)).not.toBeInTheDocument()
    expect(screen.getByText("statement:aapl")).toBeInTheDocument()
    expect(screen.getByText("Reviewed manually")).toBeInTheDocument()
  })
})
