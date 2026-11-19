import { expect, test } from "@playwright/test";
import { VP, bs1k, btn, cfFixture, gotoReady, installApiMocks, isFixture, lineageFixture, noHScroll, reconStats, tid, txt, vis } from "./helpers";

const AID = "55555555-5555-4555-8555-555555555555";
const routes = {
  "/api/reconciliation/stats": reconStats({ total_transactions: 10, matched_transactions: 9, unmatched_transactions: 1, auto_accepted: 9, match_rate: 0.9 }),
  "/api/reports/currencies": ["SGD", "USD"], "/api/users/me/settings/base-currency": { base_currency: "SGD" },
  "/api/reports/income-statement*": isFixture({ income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "6000.00" }], expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "2400.00" }], total_income: "6000.00", total_expenses: "2400.00", net_income: "3600.00" }),
  "/api/reports/cash-flow*": cfFixture({ summary: { operating_activities: "3600.00", investing_activities: "0.00", financing_activities: "0.00", net_cash_flow: "3600.00", beginning_cash: "0.00", ending_cash: "3600.00" } }),
  "/api/reports/balance-sheet*": bs1k(AID, "Checking"), "/api/reports/account-lineage*": lineageFixture(AID, "Checking", "ASSET", "l1", "e1"),
};

test.describe("AC22.3.6 report cockpit + drill-down smoke", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "rc", routes));
  for (const { name, width, height } of VP) {
    test(`${name} shows the report tabs and the statement cards and drills a balance-sheet amount`, async ({ page }) => {
      await gotoReady(page, "/reports", { width, height }); const tabs = page.getByRole("tablist", { name: "Report tabs" });
      for (const tab of ["Overview", "Balance sheet", "Income statement", "Cash flow", "Full package"]) await vis(tabs.getByRole("tab", { name: tab }));
      const card = tid(page, "cockpit-card-balance-sheet");
      await expect(card).toContainText("Net worth"); await expect(card).toContainText("SGD 1,000"); await noHScroll(page, false);
      await tabs.getByRole("tab", { name: "Balance sheet" }).click(); await expect(page).toHaveURL(/\/reports\?tab=balance-sheet$/);
      await btn(page, /View source transactions for Checking/i).click(); await vis(txt(page, "Salary deposit")); await noHScroll(page, false);
    });
  }
});
// AC-reporting.fe-ia-reports.6
