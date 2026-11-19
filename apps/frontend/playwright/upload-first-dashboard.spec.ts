import { expect, test } from "@playwright/test";
import { VP, att, bs1k, cfFixture, emptyList, gotoReady, hdg, homeRoutes, installApiMocks, isFixture, lnk, noHScroll, reg, tid, vis, wfEvent, wfSession, wfStatus } from "./helpers";

const s = wfSession("us", { event_counts: { unread: 2, action_required: 1, blocked: 0 } });
const routes = homeRoutes({
  "/api/workflow/status": wfStatus({ event_counts: { unread: 2, action_required: 1, blocked: 0 }, active_session: s }),
  "/api/workflow/events": { total: 2, sessions: [s], items: [wfEvent("r", "u", "us"), wfEvent("p", "u", "us", { family: "ledger.auto_posted", severity: "success", status: "read", title: "Posted", action_href: "/journal", report_impact: "ready" })] },
  "/api/reconciliation/transfers/pending": emptyList(),
  "/api/reports/balance-sheet*": bs1k(), "/api/reports/income-statement*": isFixture({ end_date: "2026-06-03" }), "/api/reports/cash-flow*": cfFixture({ end_date: "2026-06-03" }),
  "/api/reports/currencies": ["SGD", "USD"], "/api/users/me/settings/base-currency": { base_currency: "SGD" },
});

test.describe("AC19.4.7 upload-first dashboard smoke", () => {
  for (const { name, width, height } of VP) {
    test(`${name} renders the action banner before the statement cockpit`, async ({ page }) => {
      await installApiMocks(page, "uh", routes); await gotoReady(page, "/", { width, height });
      const banner = reg(page, "Needs attention"); await vis(hdg(banner, "An item needs your review"));
      await att(lnk(banner, "Review required"), "href", "/review"); await expect(banner).toHaveCount(1);
      const cockpit = page.getByLabel("Three-statement cockpit", { exact: true });
      await expect(tid(cockpit, "cockpit-card-balance-sheet")).toContainText("SGD 1,000");
      const b1 = await banner.boundingBox(), b2 = await cockpit.boundingBox();
      expect(b1 && b2 && b1.y < b2.y).toBe(true); await noHScroll(page);
    });
  }
});
// AC-reporting.fe-remainder-reports.10
