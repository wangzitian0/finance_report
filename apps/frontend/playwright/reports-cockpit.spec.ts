import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const ASSET_ACCOUNT_ID = "55555555-5555-4555-8555-555555555555";

async function installReportMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "reports-cockpit-user");
    localStorage.setItem("finance_user_email", "reports-cockpit@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/income/annualized") {
      body = { annualized_total: "120000.00", currency: "SGD" };
    } else if (path === "/api/reconciliation/stats") {
      body = {
        total_transactions: 10,
        matched_transactions: 9,
        unmatched_transactions: 1,
        pending_review: 0,
        auto_accepted: 9,
        match_rate: 0.9,
        score_distribution: {},
      };
    } else if (path === "/api/reports/currencies") {
      body = ["SGD", "USD"];
    } else if (path.startsWith("/api/reports/balance-sheet")) {
      body = {
        as_of_date: "2026-06-04",
        currency: "SGD",
        assets: [{ account_id: ASSET_ACCOUNT_ID, name: "Checking", type: "ASSET", parent_id: null, amount: "1000.00" }],
        liabilities: [],
        equity: [],
        total_assets: "1000.00",
        total_liabilities: "0.00",
        total_equity: "1000.00",
        net_income: "0.00",
        unrealized_fx_gain_loss: "0.00",
        net_worth_adjustment_gain_loss: "0.00",
        fx_warnings: [],
        equation_delta: "0.00",
        is_balanced: true,
      };
    } else if (path.startsWith("/api/reports/account-lineage")) {
      body = {
        account_id: ASSET_ACCOUNT_ID,
        account_name: "Checking",
        account_type: "ASSET",
        currency: "SGD",
        as_of_date: "2026-06-04",
        start_date: null,
        total: "1000.00",
        lines: [
          {
            journal_line_id: "66666666-6666-4666-8666-666666666666",
            journal_entry_id: "77777777-7777-4777-8777-777777777777",
            entry_date: "2026-05-10",
            memo: "Salary deposit",
            direction: "DEBIT",
            original_amount: "1000.00",
            original_currency: "SGD",
            amount: "1000.00",
          },
        ],
      };
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function expectNoDocumentHorizontalScroll(page: Page) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
}

test.describe("AC22.3.6 report cockpit + drill-down smoke", () => {
  test.beforeEach(async ({ page }) => {
    await installReportMocks(page);
  });

  for (const { label, width, height } of [
    { label: "desktop", width: 1440, height: 1000 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    // AC-reporting.fe-ia-reports.6
    test(`${label} shows the four blocks and drills a balance-sheet amount`, async ({ page }) => {
      await page.setViewportSize({ width, height });

      await page.goto("/reports", { waitUntil: "networkidle" });
      for (const title of ["Balance Sheet", "Income Statement", "Annualized Income", "Reconciliation coverage"]) {
        await expect(page.getByText(title, { exact: true })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      }
      await expect(page.getByRole("button", { name: /More reports/i })).toBeVisible();
      await expectNoDocumentHorizontalScroll(page);

      await page.goto("/reports/balance-sheet", { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /View source transactions for Checking/i }).click();
      await expect(page.getByText("Salary deposit")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});
