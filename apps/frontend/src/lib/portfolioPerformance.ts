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
/** The label for a cost or a profit that no recorded purchase supports (#2920). */
export const NO_PURCHASE_RECORDED = "No purchase recorded";

export interface MarketValuePerformance {
    /** Total unrealized market-value gain/loss, or null when a holding has no recorded purchase. */
    unrealizedPnl: string | null;
    /** Sum of per-holding cost basis, or null when a holding has no recorded purchase. */
    totalCostBasis: string | null;
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
    const totalMarketValue = sumAmounts(holdings.map((holding) => holding.market_value));
    const costs = holdings.map((holding) => holding.cost_basis);
    const unrealizedPnl = schedule.unrealized_pnl;
    // The backend owns the rule: it sends a null total when one held position has no recorded purchase.
    // A disposed row can have a null cost while the total is known; such a row adds nothing to the cost.
    if (unrealizedPnl == null) {
        return {
            unrealizedPnl: null,
            totalCostBasis: null,
            totalMarketValue: totalMarketValue.toFixed(2),
            returnOnCostPercent: null,
        };
    }
    const totalCostBasis = sumAmounts(costs.filter((cost): cost is string => cost != null));

    let returnOnCostPercent: string | null = null;
    if (compareAmounts(totalCostBasis, "0") !== 0) {
        returnOnCostPercent = formatPercentValueFromParts(unrealizedPnl, totalCostBasis.toString());
    }

    return {
        unrealizedPnl,
        totalCostBasis: totalCostBasis.toFixed(2),
        totalMarketValue: totalMarketValue.toFixed(2),
        returnOnCostPercent,
    };
}
