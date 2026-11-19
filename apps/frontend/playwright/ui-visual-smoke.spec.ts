import { expect, test, type Page } from "@playwright/test";
import { T, gotoReady, hdg, installApiMocks, noHScroll, reviewQueue, stmtFixture, tid, transfersSummary, vis } from "./helpers";

const SF = "visual-smoke-statement-june-2026.pdf", VT = "Visual smoke transaction";
const routes = {
  "/api/accounts": { items: [{ id: "cash-visual", name: "Operating Cash", code: "1010", type: "ASSET", currency: "SGD", balance: "12500.00", is_active: true }], total: 1 },
  "/api/reconciliation/transfers/summary": transfersSummary(),
  "/api/statements": { items: [stmtFixture("stmt-visual", { original_filename: SF, confidence_score: 94, transactions: [{ id: "t1", amount: "123.45", description: VT }] })], total: 1 },
  "/api/statements/pending-review": { items: [{ id: "stmt-visual" }], total: 1 },
  "/api/statements/stmt-visual*": stmtFixture("stmt-visual", { account_id: "cash-visual", original_filename: SF, transactions: [{ id: "txn-visual-1", txn_date: "2026-06-05", description: VT, amount: "123.45", direction: "OUT", currency: "SGD", confidence: "high", confidence_tier: "high" }] }),
  "/api/reconciliation/review-queue": reviewQueue(),
};
async function checkPage(page: Page, path: string, heading: string, mobile: boolean, text?: string) {
  await gotoReady(page, path);
  if (mobile) await vis(page.getByRole("navigation", { name: "Primary" }));
  else { await vis(page.getByRole("navigation", { name: "Sidebar navigation" })); await expect(page.getByRole("navigation", { name: "Open workspace tabs" })).toBeVisible(); }
  await vis(hdg(page, heading)); await noHScroll(page); expect((await page.screenshot({ fullPage: true })).byteLength).toBeGreaterThan(T); if (text) await expect(page.getByText(text)).toBeVisible();
}

for (const cfg of [{ label: "desktop", mobile: false, vp: { width: 1440, height: 1000 }, sel: "stage1-desktop-transaction-region" }, { label: "mobile", mobile: true, vp: { width: 390, height: 844 }, sel: "stage1-mobile-transaction-card-txn-visual-1" }] as const) {
  test.describe(`AC16.30.5 ${cfg.label} visual smoke`, () => {
    test.use(cfg.mobile ? { viewport: cfg.vp, isMobile: true, hasTouch: true } : { viewport: cfg.vp });
    test.beforeEach(({ page }) => installApiMocks(page, "v", routes));
    test("captures representative app-shell, accounts, statements, and review pages", async ({ page }) => {
      await checkPage(page, "/settings?tab=accounts", "Accounts", cfg.mobile, "Operating Cash");
      await checkPage(page, "/upload", "Upload", cfg.mobile, SF);
      await checkPage(page, "/statements/stmt-visual", SF, cfg.mobile);
      await expect(tid(page, cfg.sel).getByText(VT)).toBeVisible();
    });
  });
}
// AC-meta.fe-app-shell.34
