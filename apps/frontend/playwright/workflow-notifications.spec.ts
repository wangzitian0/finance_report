import { expect, test } from "@playwright/test";
import { VP, att, bs1k, btn, gotoReady, hdg, homeRoutes, installApiMocks, isFixture, lnk, noHScroll, reg, reviewQueue, vis, wfEvent, wfSession, wfStatus } from "./helpers";

const s = wfSession("ws", { source_count: 3, event_counts: { unread: 2, action_required: 1, blocked: 1 } });
const ev = { total: 3, sessions: [s], items: [
  wfEvent("b", "u", "ws", { family: "reconciliation.blocked", severity: "blocked", title: "Reconciliation blocked", action_href: "/reconciliation?tab=unmatched" }),
  wfEvent("r", "u", "ws", { occurred_at: "2026-06-03T07:00:00Z", title: "Review required" }),
  wfEvent("ok", "u", "ws", { occurred_at: "2026-06-03T06:00:00Z", family: "ledger.auto_posted", severity: "success", status: "read", title: "Posted", action_href: "/journal", report_impact: "ready" }),
] };

test.describe("AC19.3.7 workflow notification smoke", () => {
  for (const { name, width, height } of VP) {
    test(`${name} shows workflow badge, inbox, and the Home action banner`, async ({ page }) => {
      await installApiMocks(page, "wf", homeRoutes({ "/api/workflow/status": wfStatus({ event_counts: { unread: 2, action_required: 1, blocked: 1 }, active_session: s }), "/api/workflow/events": ev, "/api/workflow/events/*": ev.items[0], "/api/accounts": { items: [{ id: "c", name: "Cash", type: "ASSET", currency: "SGD", is_active: true }], total: 1 }, "/api/statements": { items: [{ id: "st", status: "approved" }], total: 1 }, "/api/statements/pending-review": { items: [{ id: "st" }], total: 1 }, "/api/reconciliation/review-queue": reviewQueue(), "/api/reports/balance-sheet*": bs1k(), "/api/reports/income-statement*": isFixture({ end_date: "2026-06-03" }) }));
      await gotoReady(page, "/", { width, height });
      const b = reg(page, "Needs attention"); await vis(hdg(b, "An item needs your review")); await att(lnk(b, "Review required"), "href", "/review");
      await btn(page, /Workflow events/i).click();
      const d = page.getByRole("dialog", { name: "Workflow events" }); await expect(d).toBeVisible();
      await expect(hdg(d, "Upload-to-report session")).toBeVisible();
      await expect(d.getByRole("list", { name: "Upload-to-report session timeline" })).toBeVisible();
      await att(lnk(d, "Open", false).first(), "href", "/reconciliation?tab=unmatched"); await noHScroll(page);
    });
  }
});
// AC-platform.fe-workflow.4
