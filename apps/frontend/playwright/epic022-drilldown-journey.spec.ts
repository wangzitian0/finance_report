import { expect, test, type Page } from "@playwright/test";

// AC22.4.6 — end-to-end drill-down journey: a Balance Sheet amount opens the
// contributing journal lines, and selecting a line reveals the full evidence
// chain down to the source document.

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const ACCOUNT_ID = "33333333-3333-4333-8333-333333333333";
const JOURNAL_LINE_ID = "44444444-4444-4444-8444-444444444444";

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "drill-user");
    localStorage.setItem("finance_user_email", "drill@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/reports/currencies") {
      body = ["SGD"];
    } else if (path.startsWith("/api/reports/balance-sheet")) {
      body = {
        as_of_date: "2026-06-04",
        currency: "SGD",
        assets: [{ account_id: ACCOUNT_ID, name: "Checking", type: "ASSET", parent_id: null, amount: "1000.00" }],
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
        account_id: ACCOUNT_ID,
        account_name: "Checking",
        account_type: "ASSET",
        currency: "SGD",
        as_of_date: "2026-06-04",
        start_date: null,
        total: "1000.00",
        lines: [
          {
            journal_line_id: JOURNAL_LINE_ID,
            journal_entry_id: "55555555-5555-4555-8555-555555555555",
            entry_date: "2026-05-10",
            memo: "Salary deposit",
            direction: "DEBIT",
            original_amount: "1000.00",
            original_currency: "SGD",
            amount: "1000.00",
          },
        ],
      };
    } else if (path.startsWith("/api/evidence/lineage")) {
      body = {
        anchor: null,
        max_depth: 6,
        blockers: [],
        edges: [],
        nodes: [
          { id: "n1", node_kind: "ledger_line", entity_type: "journal_line", entity_id: JOURNAL_LINE_ID, properties: {} },
          { id: "n2", node_kind: "extracted_record", entity_type: "bank_statement_transaction", entity_id: "s1", properties: {} },
          { id: "n3", node_kind: "atomic_fact", entity_type: "atomic_transaction", entity_id: "a1", properties: {} },
          { id: "n4", node_kind: "source_document", entity_type: "uploaded_document", entity_id: "d1", properties: {} },
        ],
      };
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test.describe("AC22.4.6 report drill-down to source journey", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  for (const { label, width, height } of [
    { label: "desktop", width: 1440, height: 1000 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    test(`${label}: a Balance Sheet amount drills to its contributing line and on to the source document`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });
      await page.goto("/reports/balance-sheet", { waitUntil: "networkidle" });

      // 1) Click the account amount to open its contributing transactions.
      await page
        .getByRole("button", { name: "View source transactions for Checking" })
        .click({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(page.getByText("Salary deposit")).toBeVisible();

      // 2) Drill the contributing line into its full evidence lineage.
      await page.getByText("Salary deposit").click();
      await expect(page.getByText("source document")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    });
  }
});
