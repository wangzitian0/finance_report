import { expect, test } from "@playwright/test";
import { btn, gone, gotoReady, hdg, installApiMocks, mobileUxResolver, noHScroll, tid, txt, vis } from "./helpers";

const ST1 = "stage1-mobile-transaction-card-txn-mobile-1", ST2 = "stage2-mobile-match-card-match-mobile-1", MR = "Long reconciliation match needing mobile approval";
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.describe.configure({ mode: "serial" });
test.beforeEach(({ page }) => installApiMocks(page, "mobile", mobileUxResolver()));

test("AC16.25.1 mobile review routes avoid document horizontal scrolling", async ({ page }) => {
  await gotoReady(page, "/audit"); await vis(tid(page, "ai-suggestions-mobile-list")); await noHScroll(page);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible(); await noHScroll(page);
  await gotoReady(page, "/journal"); await txt(page, "Mobile review sample entry").click();
  await vis(tid(page, "journal-lines-mobile")); await noHScroll(page);
});

test("AC16.25.2 AI suggestions mobile cards expose feedback actions", async ({ page }) => {
  await gotoReady(page, "/audit"); const c = tid(page, "ai-suggestion-mobile-card-suggestion-mobile"); await vis(c);
  await expect(txt(c, "Long mobile transaction description")).toBeVisible(); await expect(c.getByLabel("Corrected value")).toBeVisible();
  for (const n of ["Accept", "Reject", "Edit-then-Accept"]) await expect(btn(c, n)).toBeVisible(); await noHScroll(page);
});

test("AC16.26.1 stage 1 mobile review exposes read-only transaction cards and completion actions", async ({ page }) => {
  await gotoReady(page, "/statements/stmt-mobile"); await vis(tid(page, ST1));
  for (const l of ["Description for txn-mobile-1", "Amount for txn-mobile-1"]) await gone(page.getByLabel(l));
  await gone(btn(page, "Approve Edits (1)")); for (const n of ["Reject", "Approve"]) await expect(btn(page, n)).toBeVisible(); await noHScroll(page);
});

test("AC16.26.2 stage 2 mobile queue exposes selectable match cards and batch actions", async ({ page }) => {
  await gotoReady(page, "/reconciliation?tab=review-queue"); const c = tid(page, ST2); await vis(c);
  await expect(txt(c, MR)).toBeVisible(); await c.getByRole("checkbox", { name: "Select match match-mobile-1" }).check();
  for (const n of ["Reject", "Approve Selected"]) await expect(btn(page, n)).toBeVisible(); await noHScroll(page);
});

test("AC16.26.3 stage 2 run review preserves mobile approval gate and match workflow", async ({ page }) => {
  await gotoReady(page, "/audit?run_id=run-mobile-1"); await expect(txt(page, "Run approval gate")).toBeVisible();
  await expect(btn(page, "Approve Run")).toBeVisible(); await vis(tid(page, ST2)); await noHScroll(page);
});

test("AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls", async ({ page }) => {
  await gotoReady(page, "/settings?tab=accounts"); await vis(hdg(page, "Accounts")); await expect(tid(page, "account-row-account-mobile-long")).toBeVisible(); await noHScroll(page);
  const m = await tid(page, "account-row-account-mobile-long").evaluate((row) => { const q = (f: string) => row.querySelector(`[data-account-field='${f}']`)?.getBoundingClientRect(); const n = q("identity"), b = q("balance"), a = q("actions"); return { has: Boolean(n && b && a), nb: n?.bottom ?? 0, bt: b?.top ?? 0, bb: b?.bottom ?? 0, at: a?.top ?? 0 }; });
  expect(m.has && m.nb <= m.bt && m.bb <= m.at).toBe(true);
});

test.describe("375px mobile review proof", () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  test("AC8.13.76 stage 1 and stage 2 review routes remain usable at 375px", async ({ page }) => {
    for (const [u, id, b] of [["/statements/stmt-mobile", ST1, "Approve"], ["/reconciliation?tab=review-queue", ST2, "Approve Selected"], ["/audit?run_id=run-mobile-1", ST2, "Approve Run"]]) {
      await gotoReady(page, u); await vis(tid(page, id)); await expect(btn(page, b)).toBeVisible(); await noHScroll(page);
    }
  });
});

test.describe("1440px desktop review proof", () => {
  test.use({ viewport: { width: 1440, height: 1000 }, isMobile: false, hasTouch: false });
  for (const [t, u, r, x] of [
    ["AC8.13.82/AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px", "/statements/stmt-mobile", "stage1-desktop-transaction-region", "Long mobile grocery transaction from a bank statement"],
    ["AC8.13.82/AC16.27.3 desktop stage 2 review keeps pending matches readable at 1440px", "/reconciliation?tab=review-queue", "stage2-desktop-match-region", MR],
  ]) {
    test(t, async ({ page }) => { await gotoReady(page, u); const g = tid(page, r); await vis(g); await expect(txt(g, x)).toBeVisible(); const m = await g.evaluate((el) => ({ cw: el.clientWidth, sw: el.scrollWidth })); expect(m.sw).toBeLessThanOrEqual(m.cw); await noHScroll(page); });
  }
});
// AC-extraction.fe-stage1-review.10 AC-extraction.fe-stage1-review.11 AC-ledger.fe-accounts2.1 AC-reconciliation.fe-stage2-review.12 AC-reconciliation.fe-stage2-review.13 AC-testing.fe-coverage.2 AC-testing.fe-coverage.3 EPIC-011
