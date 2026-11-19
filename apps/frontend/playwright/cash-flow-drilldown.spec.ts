import { expect, test } from "@playwright/test";
import { VP, btn, cfFixture, gotoReady, installApiMocks, lineageFixture, noHScroll, txt, vis, wfStatus } from "./helpers";

const routes = {
  "/api/workflow/status": wfStatus({ primary_state: "ready", next_action: null, report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } }),
  "/api/reports/currencies": ["SGD", "USD"],
  "/api/reports/cash-flow": cfFixture({ start_date: "2026-05-01", end_date: "2026-06-01", operating: [{ line_id: "op", category: "Operating", subcategory: "Salary", amount: "5000.00", description: "Inflow - Salary", account_id: "acc-salary", event_count: 1 }], summary: { operating_activities: "5000.00", investing_activities: "0.00", financing_activities: "0.00", net_cash_flow: "5000.00", beginning_cash: "1000.00", ending_cash: "6000.00" }, lineage_summary: { event_count: 1, classified_event_count: 1, unclassified_event_count: 0, opening_stock_event_count: 0 }, proof_state: "proven" }),
  "/api/reports/account-lineage": lineageFixture("acc-salary", "Salary", "INCOME", "l1", "e1", "5000.00"),
};

test.describe("AC22.7.4 cash-flow drill-down smoke", () => {
  for (const { name, width, height } of VP) {
    test(`${name} opens account-lineage drawer from a cash-flow amount`, async ({ page }) => {
      await installApiMocks(page, "cf", routes); await gotoReady(page, "/reports?tab=cash-flow", { width, height });
      await btn(page, /View source transactions for Salary/i).click();
      const d = page.getByRole("dialog", { name: "Sources · Salary" });
      await vis(d); await expect(txt(d, "Salary deposit")).toBeVisible(); await noHScroll(page);
    });
  }
});
// AC-reporting.fe-ia-reports.13
