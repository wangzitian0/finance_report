import { expect, test } from "@playwright/test";
import { VP, att, emptyList, gotoReady, hdg, installApiMocks, lnk, noHScroll, reconStats, reg, stmtFixture, txt, vis } from "./helpers";

const routes = {
  "/api/statements": { total: 1, items: [stmtFixture("stmt-1", { original_filename: "march-statement.pdf", confidence_score: 72, balance_validated: false })] },
  "/api/reconciliation/stats": reconStats({ total_transactions: 50, matched_transactions: 40, unmatched_transactions: 4, pending_review: 2, auto_accepted: 38, match_rate: 80 }),
  "/api/reconciliation/transfers/pending": emptyList(), "/api/reconciliation/unmatched": emptyList(),
};

test.describe("AC22.6.4 attention surface smoke", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "attention", routes));
  for (const { name, width, height } of VP) {
    test(`${name} renders the attention queue ranked by confidence without overflow`, async ({ page }) => {
      await gotoReady(page, "/audit", { width, height }); await vis(hdg(page, "Needs Confirmation"));
      for (const l of [txt(page, /unmatched transaction/i), txt(page, "march-statement.pdf"), page.locator('a[href="/statements/stmt-1?from=attention"]'), page.locator('a[href="/reconciliation?tab=unmatched&from=attention"]')]) await expect(l).toBeVisible();
      await noHScroll(page, false);
    });
    test(`${name} surfaces the Home action banner linking to the audit queue`, async ({ page }) => {
      await gotoReady(page, "/", { width, height }); const b = reg(page, "Needs attention"); await vis(b);
      await expect(hdg(b, /^\d+ items? needs? you$/)).toBeVisible(); await att(lnk(b, "Open Needs you"), "href", "/audit?tab=needs-you"); await noHScroll(page, false);
    });
  }
});
// AC-reconciliation.fe-ia-reconciliation.5 AC22.11.3 EPIC-022
