import { expect, test } from "@playwright/test";
import { VP, gotoReady, hdg, homeRoutes, installApiMocks, lnk, noHScroll, vis } from "./helpers";

const Z = "0.00", D = "2026-06-01", S = "SGD";
const sh = (asset_identifier: string, quantity: string, cost_basis: string, market_value: string, unrealized_pnl: string) => ({ asset_identifier, quantity, cost_basis, market_value, unrealized_pnl, realized_pnl: Z, dividend_income: Z, currency: S });
const h = (id: string, s: string, q: string, cb: string, mv: string, p: string, provenance: string | null) => ({ ...sh(s, q, cb, mv, p), id, user_id: "u", account_id: "b", account_name: "IBKR", unrealized_pnl_percent: "5.00", acquisition_date: D, disposal_date: null, status: "active", sector: "Tech", geography: "US", provenance });
const hs = [sh("IMP", "10", "1000.00", "1250.00", "250.00"), sh("UNK", "5", "500.00", "525.00", "25.00")];
const routes = homeRoutes({
  "/api/workflow/status": { primary_state: "ready", next_action: null, report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } },
  "/api/portfolio/holdings": { items: [h("i1", "IMP", "10", "1000.00", "1250.00", "250.00", "imported"), h("u1", "UNK", "5", "500.00", "525.00", "25.00", null)], total: 2, warnings: [] },
  "/api/portfolio/summary": { total_market_value: "1775.00", total_cost_basis: "1500.00", total_unrealized_pnl: "275.00", total_unrealized_pnl_percent: "18.33", total_realized_pnl: Z, total_realized_pnl_percent: Z, net_pnl: "275.00", net_pnl_percent: "18.33", holdings_count: 2, active_positions_count: 2, disposed_positions_count: 0, currency: S, realized_pnl_ytd: Z, dividend_income_ytd: Z },
  "/api/portfolio/allocation/*": [], "/api/reports/net-worth/allocation": { as_of_date: D, currency: S, include_restricted: true, total_assets: "1775.00", total_liabilities: Z, net_worth: "1775.00", rows: [] },
  "/api/portfolio/performance/report-schedule": { period_start: D, period_end: D, as_of_date: D, currency: S, xirr: "8.00", time_weighted_return: "6.00", money_weighted_return: "7.00", dividend_yield: "1.50", realized_pnl: Z, unrealized_pnl: "275.00", dividend_income: Z, holdings: hs, allocation: [], data_freshness: { latest_price_date: D, market_data_provider: "s", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: [], notes: [] },
});

test.describe("AC22.10.3 portfolio provenance smoke", () => {
  for (const { name, width, height } of VP) {
    test(`${name} labels only imported holdings with provenance`, async ({ page }) => {
      await installApiMocks(page, "pf", routes); await gotoReady(page, "/portfolio", { width, height });
      await vis(hdg(page, "Portfolio")); for (const s of ["IMP", "UNK"]) await expect(lnk(page, s)).toBeVisible();
      await expect(page.getByText("Imported")).toHaveCount(1); await noHScroll(page);
    });
  }
});
// AC-portfolio.fe-ia-portfolio.3
