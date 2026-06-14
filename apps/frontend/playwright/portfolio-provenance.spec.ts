import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const holdings = [
  {
    id: "imported-holding",
    user_id: "portfolio-provenance-smoke-user",
    account_id: "broker-account",
    account_name: "IBKR",
    asset_identifier: "IMP",
    quantity: "10",
    cost_basis: "1000.00",
    market_value: "1250.00",
    unrealized_pnl: "250.00",
    unrealized_pnl_percent: "25.00",
    currency: "SGD",
    acquisition_date: "2026-01-01",
    disposal_date: null,
    status: "active",
    sector: "Technology",
    geography: "US",
    provenance: "imported",
  },
  {
    id: "unknown-holding",
    user_id: "portfolio-provenance-smoke-user",
    account_id: "broker-account",
    account_name: "IBKR",
    asset_identifier: "UNK",
    quantity: "5",
    cost_basis: "500.00",
    market_value: "525.00",
    unrealized_pnl: "25.00",
    unrealized_pnl_percent: "5.00",
    currency: "SGD",
    acquisition_date: "2026-02-01",
    disposal_date: null,
    status: "active",
    sector: "Other",
    geography: "US",
    provenance: null,
  },
];

const netWorthAllocation = {
  as_of_date: "2026-06-01",
  currency: "SGD",
  include_restricted: true,
  total_assets: "1775.00",
  total_liabilities: "0.00",
  net_worth: "1775.00",
  rows: [],
};

async function installPortfolioMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "portfolio-provenance-smoke-user");
    localStorage.setItem("finance_user_email", "portfolio-provenance@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = {
        primary_state: "ready",
        next_action: null,
        report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
        event_counts: { unread: 0, action_required: 0, blocked: 0 },
      };
    } else if (path === "/api/portfolio/holdings") {
      body = holdings;
    } else if (path === "/api/portfolio/summary") {
      body = {
        total_market_value: "1775.00",
        total_cost_basis: "1500.00",
        total_unrealized_pnl: "275.00",
        total_unrealized_pnl_percent: "18.33",
        total_realized_pnl: "0.00",
        total_realized_pnl_percent: "0.00",
        net_pnl: "275.00",
        net_pnl_percent: "18.33",
        holdings_count: 2,
        active_positions_count: 2,
        disposed_positions_count: 0,
        currency: "SGD",
        realized_pnl_ytd: "0.00",
        dividend_income_ytd: "0.00",
      };
    } else if (path === "/api/portfolio/performance") {
      body = { xirr: "8.00", time_weighted_return: "6.00", money_weighted_return: "7.00" };
    } else if (path.startsWith("/api/portfolio/allocation/")) {
      body = [];
    } else if (path === "/api/reports/net-worth/allocation") {
      body = netWorthAllocation;
    } else if (path === "/api/portfolio/performance/report-schedule") {
      body = {
        period_start: "2026-01-01",
        period_end: "2026-06-01",
        as_of_date: "2026-06-01",
        currency: "SGD",
        xirr: "8.00",
        time_weighted_return: "6.00",
        money_weighted_return: "7.00",
        dividend_yield: "1.50",
        realized_pnl: "0.00",
        unrealized_pnl: "275.00",
        dividend_income: "0.00",
        holdings: [
          {
            asset_identifier: "IMP",
            quantity: "10",
            cost_basis: "1000.00",
            market_value: "1250.00",
            unrealized_pnl: "250.00",
            realized_pnl: "0.00",
            dividend_income: "0.00",
            currency: "SGD",
          },
          {
            asset_identifier: "UNK",
            quantity: "5",
            cost_basis: "500.00",
            market_value: "525.00",
            unrealized_pnl: "25.00",
            realized_pnl: "0.00",
            dividend_income: "0.00",
            currency: "SGD",
          },
        ],
        allocation: [],
        data_freshness: {
          latest_price_date: "2026-06-01",
          market_data_provider: "smoke-fixture",
          stale: false,
          stale_holdings: [],
          manual_override_basis: null,
        },
        source_links: [],
        notes: [],
      };
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function expectNoDocumentHorizontalScroll(page: Page) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    scrollX: window.scrollX,
  }));

  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  expect(metrics.scrollX).toBe(0);
}

test.describe("AC22.10.3 portfolio provenance smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} labels only imported holdings with provenance`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installPortfolioMocks(page);

      await page.goto("/portfolio", { waitUntil: "networkidle" });

      await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible({
        timeout: COLD_ROUTE_TIMEOUT_MS,
      });
      await expect(page.getByRole("link", { name: "IMP" })).toBeVisible();
      await expect(page.getByRole("link", { name: "UNK" })).toBeVisible();
      await expect(page.getByText("Imported")).toHaveCount(1);
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});
