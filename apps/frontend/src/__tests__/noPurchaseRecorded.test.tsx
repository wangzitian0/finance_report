import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HoldingDetail } from "@/components/portfolio/Holdings";
import { InvestmentPerformanceSchedule } from "@/components/portfolio/InvestmentPerformanceSchedule";
import { PerformanceCard } from "@/components/portfolio/PortfolioSummary";
import { PackageSectionCards } from "@/components/reports/package/shared";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/packageTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

// #2920: a position without a recorded purchase has no cost and no profit. Each surface says so in words.
describe("empty cost and profit without a recorded purchase", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => {
    api.mockReset();
  });

  it("PerformanceCard shows the label and no cost in place of a number", () => {
    render(<PerformanceCard schedule={F.makeSchedule({ unrealized_pnl: null })} />);
    expect(screen.getByText("No purchase recorded")).toBeInTheDocument();
    expect(screen.getByText("vs cost not available")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("InvestmentPerformanceSchedule shows the label and no cost in place of a number", () => {
    render(<InvestmentPerformanceSchedule schedule={F.makeSchedule({ unrealized_pnl: null })} />);
    expect(screen.getByText("No purchase recorded")).toBeInTheDocument();
    expect(screen.getByText("vs cost not available")).toBeInTheDocument();
  });

  it("the report package says that the unrealized profit is not available", () => {
    const sections = F.makePackageDoc().sections;
    const withNull = { ...sections, investment_performance: F.makeSchedule({ unrealized_pnl: null }) };
    render(<PackageSectionCards sections={withNull as never} includeRestricted={null} />);
    expect(screen.getByText("Unrealized P&L").nextElementSibling).toHaveTextContent("Not available");
    expect(screen.getByText("Realized P&L").nextElementSibling).not.toHaveTextContent("Not available");
  });

  it("HoldingDetail shows the label under the cost and dashes for the profit", async () => {
    F.mockDetailApi(api, [
      F.makeHolding({
        cost_basis: null,
        native_cost_basis: null,
        unrealized_pnl: null,
        unrealized_pnl_percent: null,
        cost_basis_method: "FIFO",
      }),
    ]);
    render(<HoldingDetail ticker="AAPL" />);
    await waitFor(() => expect(screen.getAllByText("Market Value").length).toBeGreaterThanOrEqual(1));
    const costCard = screen.getAllByText("Cost Basis")[0].closest(".card") as HTMLElement;
    expect(within(costCard).getByText("No purchase recorded")).toBeInTheDocument();
    const pnlCard = screen.getByText("Unrealized P&L").closest(".card") as HTMLElement;
    expect(within(pnlCard).getAllByText("—")).toHaveLength(2);
  });
});
