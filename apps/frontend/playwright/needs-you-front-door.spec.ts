import { expect, test, type Page } from "@playwright/test";
import { NVP, T, att, dqFixture, emptyList, gone, gotoReady, hdg, installApiMocks, lnk, reconStats, reg, stmtFixture, tid, txt, vis, wfStatus } from "./helpers";

const app = (id: string, ps: string, pe: string, o: Record<string, unknown> = {}) => stmtFixture(id, { status: "approved", period_start: ps, period_end: pe, ...o });
const STMTS = [app("d7", "2026-07-01", "2026-07-31"), app("d8", "2026-08-01", "2026-08-31"), app("d9", "2026-09-01", "2026-09-30"), app("d10", "2026-10-01", "2026-10-31", { status: "parsed", confidence_score: 80 }), app("ibkr", "2026-10-01", "2026-10-31", { status: "parsed", confidence_score: 20 })];
async function visBot(p: Page, h: number) { const bar = p.getByRole("navigation", { name: "Primary" }); if (!(await bar.isVisible())) return h; const b = await bar.boundingBox(); return b ? Math.min(b.y, h) : h; }

test.describe("#2646 the front door to the items that need the user", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "needs-you", { "/api/statements": { items: STMTS, total: 5 }, "/api/reconciliation/stats": reconStats({ total_transactions: 26, matched_transactions: 25, unmatched_transactions: 1, auto_accepted: 25, match_rate: 96 }), "/api/reconciliation/unmatched": { items: [{ id: "t", txn_date: "2026-10-14", description: "PayNow Transfer REF 4471", amount: "250.00", direction: "OUT", currency: "SGD" }], total: 1 }, "/api/workflow/status": wfStatus({ primary_state: "blocked", next_action: { type: "resolve_blocker", count: 1, href: "/reports?tab=package" }, event_counts: { unread: 0, action_required: 0, blocked: 1 } }), "/api/reports/data-quality": dqFixture({ score: 99, as_of_date: "2026-10-22" }) }, emptyList()));

  for (const { label, width, height } of NVP) {
    test(`AC-meta.fe-audit-queue.5 /audit shows the Needs Confirmation list in the first viewport (${label})`, async ({ page }) => {
      await gotoReady(page, "/audit", { width, height }); const q = tid(page, "needs-confirmation-queue"), rl = lnk(q, /PayNow Transfer REF 4471/); await vis(rl);
      const hb = await hdg(q, "Needs Confirmation").boundingBox(), rb = await rl.boundingBox(), bot = await visBot(page, height);
      expect(hb && rb && hb.y >= 0 && rb.y + rb.height <= bot).toBe(true);
      await att(page.getByRole("tab", { name: /Needs you/ }), "aria-selected", "true");
    });
    test(`AC-reporting.fe-period-cockpit.9 Home names the count and the first item above the statement cards (${label})`, async ({ page }) => {
      await gotoReady(page, "/", { width, height }); const b = reg(page, "Needs attention"); await vis(hdg(b, "3 items need you"));
      await att(lnk(b, "PayNow Transfer REF 4471"), "href", "/reconciliation?tab=unmatched&from=attention");
      await gone(txt(page, "A blocker holds your reports"));
      const b1 = await b.boundingBox(), b2 = await reg(page, "Three-statement cockpit").boundingBox();
      expect(b1 && b2 && b1.y + b1.height <= b2.y).toBe(true);
    });
  }
  test("AC-meta.fe-audit-queue.4 the Health tab holds the audit-ready grade while a row is unmatched", async ({ page }) => {
    await gotoReady(page, "/audit?tab=health", { width: 1280, height: 800 }); await vis(txt(page, "Open items remain", true)); await gone(txt(page, /Audit[- ]Ready/i));
  });
  test("AC-reconciliation.fe-tabs.2 /reconciliation opens on Unmatched when a row is unmatched", async ({ page }) => {
    await gotoReady(page, "/reconciliation", { width: 1280, height: 800 }); const tabs = page.getByRole("navigation", { name: "Reconciliation workspace views" });
    await expect(lnk(tabs, /Unmatched/)).toHaveAttribute("aria-current", "page", { timeout: T });
    await att(lnk(tabs, "Matches"), "href", "/reconciliation?tab=matches");
  });
});
