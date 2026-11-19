import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PerformanceCard } from "@/components/portfolio/PortfolioSummary";
import { makeSchedule } from "./helpers/packageTestFixtures";

describe("PerformanceCard", () => {
  it("renders loading and error states", () => {
    const { rerender } = render(<PerformanceCard isLoading />);
    expect(screen.getByText("Performance")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeTruthy();
    rerender(<PerformanceCard error={new Error("network error")} />);
    expect(screen.getByText("Unable to load performance metrics")).toBeInTheDocument();
  });
  it("AC17.14.4 leads with market-value performance, freshness, and omits TWR/IRR/MWR", () => {
    const base = makeSchedule();
    const { rerender } = render(<PerformanceCard schedule={base} />);
    expect(screen.getByText("Market-Value Performance")).toBeInTheDocument();
    expect(screen.getByText("Unrealized gain/loss")).toBeInTheDocument();
    expect(screen.getByText("Return on cost")).toBeInTheDocument();
    expect(screen.getByText("+10.00%")).toHaveClass("text-[var(--success)]");
    expect(screen.getByText("Prices current")).toBeInTheDocument();
    expect(screen.getByText("as of 2026-04-01")).toBeInTheDocument();
    for (const t of ["XIRR", "TWR", "MWR"]) expect(screen.queryByText(t)).not.toBeInTheDocument();

    rerender(<PerformanceCard schedule={makeSchedule({ data_freshness: { ...base.data_freshness, stale: true, stale_holdings: ["AAPL"] } })} />);
    expect(screen.getByText("Prices stale")).toHaveClass("text-[var(--error)]");

    rerender(<PerformanceCard schedule={makeSchedule({ unrealized_pnl: "-300.00", holdings: [{ ...base.holdings[0], cost_basis: "3000.00", unrealized_pnl: "-300.00" }] })} />);
    expect(screen.getByText("-10.00%")).toHaveClass("text-[var(--error)]");

    rerender(<PerformanceCard schedule={makeSchedule({ unrealized_pnl: "0.00", holdings: [] })} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });
}); // AC-portfolio.fe-assets2.19
