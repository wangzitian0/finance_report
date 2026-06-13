import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

async function installCashFlowMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "cash-flow-smoke-user");
    localStorage.setItem("finance_user_email", "cash-flow-smoke@example.com");
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
    } else if (path === "/api/reports/currencies") {
      body = ["SGD", "USD"];
    } else if (path === "/api/reports/cash-flow") {
      body = {
        start_date: "2026-05-01",
        end_date: "2026-06-01",
        currency: "SGD",
        operating: [
          {
            category: "operating",
            subcategory: "Salary",
            amount: "5000.00",
            description: "Inflow - Salary",
            account_id: "acc-salary",
          },
        ],
        investing: [],
        financing: [],
        summary: {
          operating_activities: "5000.00",
          investing_activities: "0.00",
          financing_activities: "0.00",
          net_cash_flow: "5000.00",
          beginning_cash: "1000.00",
          ending_cash: "6000.00",
        },
        fx_warnings: [],
      };
    } else if (path === "/api/reports/account-lineage") {
      body = {
        account_id: "acc-salary",
        account_name: "Salary",
        account_type: "INCOME",
        currency: "SGD",
        as_of_date: "2026-06-01",
        start_date: "2026-05-01",
        total: "5000.00",
        lines: [
          {
            journal_line_id: "33333333-3333-4333-8333-333333333333",
            journal_entry_id: "22222222-2222-4222-8222-222222222222",
            entry_date: "2026-05-25",
            memo: "Salary deposit",
            direction: "DEBIT",
            original_amount: "5000.00",
            original_currency: "SGD",
            amount: "5000.00",
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
    scrollX: window.scrollX,
  }));

  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  expect(metrics.scrollX).toBe(0);
}

test.describe("AC22.7.4 cash-flow drill-down smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} opens account-lineage drawer from a cash-flow amount`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installCashFlowMocks(page);

      await page.goto("/reports/cash-flow", { waitUntil: "networkidle" });

      await page.getByRole("button", { name: /View source transactions for Salary/i }).click();
      const drawer = page.getByRole("dialog", { name: "Sources · Salary" });
      await expect(drawer).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(drawer.getByText("Salary deposit")).toBeVisible();
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});
