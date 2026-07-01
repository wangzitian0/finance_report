import { compareAmounts, sumAmounts } from "./audit/money";
import { formatPercentValueFromParts } from "@/lib/audit/ratio/format";
import type { InvestmentPerformanceReportSchedule } from "./types";

/**
 * Market-value performance figures derived from the investment performance
 * report schedule. This is the honest "asset-dashboard answer" for #914:
 * unrealized market-value gain/loss and a simple return on cost basis tied to
 * the schedule period. It deliberately excludes TWR/IRR/MWR, which stay on the
 * reporting side as analytical measures rather than the headline answer.
 */
export interface MarketValuePerformance {
    /** Total unrealized market-value gain/loss in the schedule currency. */
    unrealizedPnl: string;
    /** Sum of per-holding cost basis in the schedule currency. */
    totalCostBasis: string;
    /** Sum of per-holding market value in the schedule currency. */
    totalMarketValue: string;
    /**
     * Unrealized return on cost basis as a percentage, or null when the cost
     * basis is zero (return is undefined). Not a time-weighted/internal rate.
     */
    returnOnCostPercent: string | null;
}

export function computeMarketValuePerformance(
    schedule: InvestmentPerformanceReportSchedule,
): MarketValuePerformance {
    const holdings = schedule.holdings ?? [];
    const totalCostBasis = sumAmounts(holdings.map((holding) => holding.cost_basis));
    const totalMarketValue = sumAmounts(holdings.map((holding) => holding.market_value));

    let returnOnCostPercent: string | null = null;
    if (compareAmounts(totalCostBasis, "0") !== 0) {
        returnOnCostPercent = formatPercentValueFromParts(schedule.unrealized_pnl, totalCostBasis.toString());
    }

    return {
        unrealizedPnl: schedule.unrealized_pnl,
        totalCostBasis: totalCostBasis.toFixed(2),
        totalMarketValue: totalMarketValue.toFixed(2),
        returnOnCostPercent,
    };
}
