import { expect, test } from "@playwright/test";
import { NVP, btn, emptyList, gone, gotoReady, installApiMocks, lnk, reg, tid, txt, vis, uploadLayoutRoutes } from "./helpers";

const BID = "2648a0b1-0000-4000-8000-0000000b0001", R = "upload-statement-row-2648a0b1-0000-4000-8000-0000000000", S = "upload-workflow-summary", B = "Statement balance check needed", IF = "Import failed";
const bRow = (p: Parameters<typeof tid>[0]) => tid(p, `upload-statement-row-${BID}`);

test.describe("#2648 upload page", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "ul", uploadLayoutRoutes(BID), emptyList()));

  test("AC-extraction.fe-upload-layout.1 has no horizontal overflow at 375 px", async ({ page }) => {
    await gotoReady(page, "/upload", { width: 375, height: 812 }); await vis(bRow(page));
    const sw = () => page.evaluate(() => document.documentElement.scrollWidth); expect(await sw()).toBeLessThanOrEqual(375);
    await tid(page, S).locator(":scope > summary").click(); await expect(txt(page, B).first()).toBeVisible(); expect(await sw()).toBeLessThanOrEqual(375);
  });

  test("AC-extraction.fe-upload-layout.2 starts the file list within 1.5 viewports at 375x812", async ({ page }) => {
    await gotoReady(page, "/upload", { width: 375, height: 812 }); await vis(bRow(page));
    expect(await page.locator("#statements").evaluate((e) => e.getBoundingClientRect().top + window.scrollY)).toBeLessThanOrEqual(812 * 1.5);
    await expect(tid(page, S)).toContainText("1 blocker"); await expect(txt(page, B).first()).toBeHidden();
  });

  for (const { label, width, height } of NVP) {
    test(`AC-extraction.fe-upload-layout.3 shows a failed import as Import failed with Retry and Delete (${label})`, async ({ page }) => {
      let retried = false;
      await page.route("**/api/portfolio/brokerage-imports", async (route) => { retried = true; await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "internal", error_id: "internal_error" }) }); });
      await gotoReady(page, "/upload", { width, height }); const row = bRow(page); await vis(row);
      await expect(txt(row, IF, true)).toBeVisible(); await expect(row).toContainText("does not state an as-of date for 2 of 2 positions");
      await expect(btn(row, "Delete Statement")).toBeVisible();
      for (const f of ["Parsing", "Ready to review", "Review & Approve"]) await gone(txt(row, f));
      await btn(row, "Retry import").click(); await expect.poll(() => retried).toBe(true); await expect(txt(row, IF, true)).toBeVisible();
    });
  }

  test("AC-extraction.fe-upload-layout.6 stacks mobile upload cards and transfers without overlap or clipping at 390x844", async ({ page }) => {
    await gotoReady(page, "/upload", { width: 390, height: 844 });
    const appRow = tid(page, `${R}12`); await vis(appRow);
    const b1 = await txt(appRow, "Approved", true).boundingBox(), b2 = await btn(appRow, "View Transactions").boundingBox();
    expect(b1 && b2 && (b1.x >= b2.x + b2.width || b1.x + b1.width <= b2.x || b1.y >= b2.y + b2.height || b1.y + b1.height <= b2.y)).toBe(true);
    expect((await txt(appRow, "2025-03-01 to 2025-03-31").boundingBox())?.height ?? 999).toBeLessThanOrEqual(40);
    expect((await lnk(tid(page, `${R}11`), "cmb_statement_fixture.pdf").boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(140);
    const pr = tid(page, `${R}13`); await expect(pr).toBeVisible();
    for (const pat of [/Opening:/, /Closing:/, /confidence/i]) await gone(txt(pr, pat));
    const t = txt(reg(page, "Transfers in flight"), "(unmatched destination) GXS Bank ••9912").first();
    await expect(t).toBeVisible(); const tb = await t.boundingBox(); expect((tb?.x ?? 0) + (tb?.width ?? 999)).toBeLessThanOrEqual(390);
  });
});
