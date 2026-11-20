import { describe, expect, it } from "vitest";
import { computeMarketValuePerformance } from "@/lib/portfolioPerformance";
import type { InvestmentPerformanceReportSchedule } from "@/lib/types";
import { makeSchedule } from "./helpers/packageTestFixtures";

describe("computeMarketValuePerformance", () => {
  it("AC17.14.4 derives totals, handles zero cost basis, and tolerates missing holdings", () => {
    expect(computeMarketValuePerformance(makeSchedule())).toMatchObject({ totalCostBasis: "3000.00", totalMarketValue: "3300.00", unrealizedPnl: "300.00", returnOnCostPercent: "10.00" });
    expect(computeMarketValuePerformance(makeSchedule({ unrealized_pnl: "0.00", holdings: [] }))).toMatchObject({ totalCostBasis: "0.00", returnOnCostPercent: null });
    expect(computeMarketValuePerformance(makeSchedule({ holdings: undefined }) as unknown as InvestmentPerformanceReportSchedule)).toMatchObject({ totalCostBasis: "0.00", returnOnCostPercent: null });
  });

  it("#2920 returns no cost total and no profit when a holding has no recorded purchase", () => {
    const base = makeSchedule();
    const withoutPurchase = makeSchedule({ unrealized_pnl: null, holdings: [{ ...base.holdings[0], cost_basis: null, unrealized_pnl: null }, ...base.holdings.slice(1)] });
    expect(computeMarketValuePerformance(withoutPurchase)).toEqual({ unrealizedPnl: null, totalCostBasis: null, totalMarketValue: "3300.00", returnOnCostPercent: null });
  });
});
