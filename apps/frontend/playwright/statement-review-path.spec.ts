import { expect, test } from "@playwright/test";
import { NVP, T, btn, gone, gotoReady, hdg, installApiMocks, reviewPathResolver, tid, txt, vis } from "./helpers";

const P = "2647a0b1-0000-4000-8000-00000000", SID = "2586a0b1-0000-4000-8000-000000002586", OCT = `${P}2647`, PDF = `${P}02f0`, APP = `${P}02a0`, LOW = "PayNow Transfer REF 4471", DR = "stage1-desktop-transaction-region", ML = "stage1-mobile-transaction-list", PV = "PDF Preview";

test.describe("AC-extraction.human-source-review.4 statement review click path", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "rv", reviewPathResolver(SID, OCT, PDF, APP, LOW)));

  test("upload list -> statement page shows a disabled Approve", async ({ page }) => {
    await gotoReady(page, "/upload"); const l = page.locator(`a[href="/statements/${SID}"]`); await vis(l); await l.click();
    await expect(page).toHaveURL(new RegExp(`/statements/${SID}$`), { timeout: T });
    await gone(page.locator(`a[href="/statements/${SID}/review"]`));
    await vis(txt(page, "Confirm source facts")); await expect(btn(page, "Approve")).toBeDisabled();
  });

  for (const [title, id, dtxt, pdf] of [
    ["AC-extraction.fe-stage1-review.22 keeps the description readable in a CSV statement at 1280 px", SID, "Salary", false],
    ["AC-extraction.fe-stage1-review.22 keeps the description readable beside a PDF preview at 1280 px", PDF, LOW, true],
  ] as const) {
    test(title, async ({ page }) => {
      await gotoReady(page, `/statements/${id}`, { width: 1280, height: 800 }); if (pdf) await vis(hdg(page, PV));
      const r = tid(page, DR), d = r.getByTitle(dtxt, { exact: true });
      await vis(d); expect((await d.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(120); await expect(r).toHaveCSS("overflow-y", "auto");
    });
  }

  for (const { label, width, height, id, preview } of [{ label: "CSV, desktop", width: 1280, height: 800, id: OCT, preview: false }, { label: "CSV, mobile", width: 375, height: 812, id: OCT, preview: false }, { label: "PDF, desktop", width: 1280, height: 800, id: PDF, preview: true }]) {
    test(`AC-extraction.fe-stage1-review.26 puts the low row first and in full on one page scroll (${label})`, async ({ page }) => {
      await gotoReady(page, `/statements/${id}`, { width, height });
      const row = width >= 1280 ? tid(page, DR).locator("tbody tr").first() : tid(page, ML).locator("article").first();
      await vis(row); await expect(row).toContainText(LOW); await expect(tid(row, "date-row-number")).toHaveText("Row 6 of 6");
      await expect(tid(page, "low-confidence-count")).toHaveText("1 low confidence · shown first");
      for (const t of ["Prior Gap (3198)", /Unexplained Statement Gap Equity \(3198\)/i]) await expect(txt(page, t)).toBeVisible();
      await expect(btn(page, "Approve")).toBeEnabled();
      const fit = await txt(row, LOW, true).evaluate((el) => ({ t: el.textContent, ov: getComputedStyle(el).textOverflow, sw: el.scrollWidth, cw: el.clientWidth }));
      expect(fit.t).toBe(LOW); expect(fit.ov).not.toBe("ellipsis"); expect(fit.sw).toBeLessThanOrEqual(fit.cw);
      await expect(hdg(page, PV)).toHaveCount(preview ? 1 : 0);
      if (width < 768) { const l = tid(page, ML), s = await l.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight })); expect(s.sh).toBe(s.ch); await expect(l.locator("article")).toHaveCount(6); }
    });
  }

  for (const { label, width, height } of NVP) {
    test(`AC-extraction.fe-stage1-review.24 shows no pending chip on an approved statement (${label})`, async ({ page }) => {
      await gotoReady(page, `/statements/${APP}`, { width, height });
      await expect(tid(page, DR).getByTitle(LOW, { exact: true })).toBeAttached({ timeout: T });
      await gone(txt(page, "pending", true));
    });
  }

  test("AC-extraction.fe-stage1-review.28 hides Import to Portfolio on bank statements and collapses unavailable PDF preview at 390x844", async ({ page }) => {
    await gotoReady(page, `/statements/${PDF}`, { width: 390, height: 844 });
    const h = hdg(page, PV); await vis(h); await gone(btn(page, /Import to Portfolio/i));
    expect((await h.locator("xpath=ancestor::div[contains(@class,'card')][1]").boundingBox())?.height ?? 999).toBeLessThanOrEqual(160);
  });
});
