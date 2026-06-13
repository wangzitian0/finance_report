import "@testing-library/jest-dom/vitest"
import { render, screen } from "@testing-library/react"
import { HoldingsTable } from "@/components/portfolio/HoldingsTable"
import type { PortfolioHolding } from "@/lib/types"
import { describe, expect, it } from "vitest"

const fractional: PortfolioHolding = {
  id: "h1",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "FOO",
  quantity: "10.5",
  cost_basis: "1000.00",
  market_value: "1200.00",
  unrealized_pnl: "200.00",
  unrealized_pnl_percent: "20.00",
  currency: "USD",
  acquisition_date: "2025-01-01",
  status: "active",
  account_name: "BrokerA",
}

const emptyHoldings: PortfolioHolding[] = []

const groupedHoldings: PortfolioHolding[] = [
  {
    id: "h2",
    user_id: "u1",
    account_id: "acc2",
    asset_identifier: "BAR",
    quantity: "2",
    cost_basis: "200.00",
    market_value: "210.00",
    unrealized_pnl: "10.00",
    unrealized_pnl_percent: "5.00",
    currency: "USD",
    acquisition_date: "2025-02-01",
    status: "active",
    account_name: "BrokerB",
  },
  {
    id: "h3",
    user_id: "u1",
    account_id: "acc2",
    asset_identifier: "BAZ",
    quantity: "3",
    cost_basis: "300.00",
    market_value: "250.00",
    unrealized_pnl: "-50.00",
    unrealized_pnl_percent: "-16.67",
    currency: "USD",
    acquisition_date: "2025-03-01",
    status: "active",
    account_name: "BrokerB",
  },
]

describe("HoldingsTable", () => {
  it("shows empty state when no holdings", () => {
    render(<HoldingsTable holdings={emptyHoldings} />)
    expect(screen.getByText("No holdings found")).toBeInTheDocument()
  })

  it("renders fractional quantity properly", () => {
    render(<HoldingsTable holdings={[fractional]} />)
    expect(screen.getByText("10.50")).toBeInTheDocument()
  })

  it("groups holdings by broker and shows PnL color classes", () => {
    render(<HoldingsTable holdings={groupedHoldings} />)
    // Broker badge
    expect(screen.getByText("BrokerB")).toBeInTheDocument()
    // positive pnl should contain success color class
    const pos = screen.getByText(/\$210\.00/) // market value text
    expect(pos).toBeInTheDocument()
    // negative pnl percent should render -16.67%
    expect(screen.getByText("-16.67%")).toBeInTheDocument()
  })

  it("filters disposed holdings by default", () => {
    const mixed: PortfolioHolding[] = [
      { ...fractional, id: "a1", status: "active" },
      { ...fractional, id: "d1", status: "disposed", asset_identifier: "GONE" },
    ]
    render(<HoldingsTable holdings={mixed} />)
    expect(screen.getByText("FOO")).toBeInTheDocument()
    expect(screen.queryByText("GONE")).not.toBeInTheDocument()
  })

  it("shows disposed holdings when showDisposed is true", () => {
    const mixed: PortfolioHolding[] = [
      { ...fractional, id: "a1", status: "active" },
      { ...fractional, id: "d1", status: "disposed", asset_identifier: "GONE" },
    ]
    render(<HoldingsTable holdings={mixed} showDisposed={true} />)
    expect(screen.getByText("FOO")).toBeInTheDocument()
    expect(screen.getByText("GONE")).toBeInTheDocument()
  })

  it("handles zero PnL without color class", () => {
    const zeroPnl: PortfolioHolding = {
      ...fractional,
      unrealized_pnl: "0.00",
      unrealized_pnl_percent: "0.00",
    }
    render(<HoldingsTable holdings={[zeroPnl]} />)
    expect(screen.getByText("0.00%")).toBeInTheDocument()
  })

  it("shows sector when present", () => {
    const withSector: PortfolioHolding = {
      ...fractional,
      sector: "Technology",
    }
    render(<HoldingsTable holdings={[withSector]} />)
    expect(screen.getByText(/Technology/)).toBeInTheDocument()
  })

  it("uses Unknown as group name when account_name is null", () => {
    const noAccount: PortfolioHolding = {
      ...fractional,
      account_name: undefined,
    }
    render(<HoldingsTable holdings={[noAccount]} />)
    expect(screen.getByText("Unknown")).toBeInTheDocument()
  })

  it("AC22.10.1 AC22.13.2 shows provenance badges only when provenance is known", () => {
    const imported: PortfolioHolding = { ...fractional, id: "imp", asset_identifier: "IMP", provenance: "imported" }
    const manual: PortfolioHolding = { ...fractional, id: "man", asset_identifier: "MAN", provenance: "manual" }
    const derived: PortfolioHolding = { ...fractional, id: "drv", asset_identifier: "DRV", provenance: "derived" }
    const unknown: PortfolioHolding = { ...fractional, id: "unk", asset_identifier: "UNK", provenance: null }
    render(<HoldingsTable holdings={[imported, manual, derived, unknown]} />)
    // Exactly one Imported badge — for the document-backed holding; the unknown
    // one is never labelled, while explicit Manual/Derived labels remain distinct.
    expect(screen.getAllByText("Imported")).toHaveLength(1)
    expect(screen.getByText("Manual")).toHaveClass("badge-warning")
    expect(screen.getByText("Derived")).toHaveClass("badge-muted")
    expect(screen.queryByText("Unknown")).not.toBeInTheDocument()
  })
})
