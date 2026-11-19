import { expect, test } from "@playwright/test";
import { VP, att, con, gotoReady, installApiMocks, lnk, noHScroll, packageDoc, reg, vis, wfStatus } from "./helpers";

const doc = packageDoc();
test.describe("AC19.8.7 AC19.8.8 AC22.8.4 AC22.19 report package smoke", () => {
  for (const { name, width, height } of VP) {
    test(`${name} renders cover, contents, and readiness before package output`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await installApiMocks(page, "rr", { "/api/workflow/status": wfStatus({ primary_state: "blocked", next_action: { type: "resolve_blocker", count: 1, href: "/upload" }, report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" }, event_counts: { unread: 1, action_required: 0, blocked: 1 } }), "/api/reports/package/snapshots": [], "/api/reports/package": doc });
      await gotoReady(page, "/reports?tab=package");
      await page.getByRole("button", { name: "US-like" }).click();
      await vis(page.getByRole("heading", { name: "Report Readiness" }));
      const cover = reg(page, "Report package cover"), toc = page.getByRole("navigation", { name: "Report package table of contents" }), r = page.locator("#package-readiness");
      for (const t of ["Personal Financial Report Package", "US-like"]) await con(cover, t);
      await att(lnk(toc, "Report Readiness", false), "href", "#package-readiness");
      await att(lnk(toc, "Balance Sheet", false), "href", "#package-section-balance_sheet");
      for (const t of ["Processing account unresolved", "Processing account balance cannot be converted to SGD: No FX rate available for USD/SGD."]) await con(r, t);
      await att(lnk(page, "Blocked", false), "href", "/upload");
      const d = r.locator("details", { hasText: "Readiness audit details" }), raw = d.getByText("processing_account_unresolved");
      await expect(d).not.toHaveAttribute("open", ""); await expect(raw).toHaveCount(2); await expect(raw.first()).toBeHidden();
      await d.getByText("Readiness audit details").click(); await expect(raw.first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Balance Sheet" })).toBeVisible();
      const b = page.locator("#package-framework-policy"); await expect(b.getByText("Personal Income")).toHaveCount(1); await con(b, "2 items");
      await noHScroll(page);
    });
  }
});
// AC-reporting.fe-ia-reports.17 AC-reporting.fe-remainder-reports.13
