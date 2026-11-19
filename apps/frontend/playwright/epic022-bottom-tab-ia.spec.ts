import { expect, test } from "@playwright/test";
import { att, btn, dqFixture, emptyList, gotoReady, hdg, installApiMocks, lnk, noHScroll, txt, vis, wfStatus } from "./helpers";

const routes = { "/api/workflow/status": wfStatus({ primary_state: "idle", next_action: null, report_readiness: { state: "ready", blocking_count: 0, href: "/reports" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } }), "/api/workflow/events": emptyList({ sessions: [] }), "/api/portfolio/holdings": emptyList({ warnings: [] }), "/api/journal-entries*": emptyList(), "/api/reports/data-quality": dqFixture({ currency: "USD" }) };

test.describe("AC22.21.7 mobile/PWA bottom-tab IA smoke", () => {
  test.beforeEach(async ({ page }) => { await installApiMocks(page, "bt", routes); await page.setViewportSize({ width: 390, height: 844 }); });
  test("the bottom bar opens the Add sheet with both ways to add", async ({ page }) => {
    await gotoReady(page, "/"); const b = btn(page.getByRole("navigation", { name: "Primary" }), "Add"); await vis(b); await b.click();
    const s = page.getByRole("dialog", { name: "Add" }); for (const t of ["Upload statement", "Manual entry"]) await expect(txt(s, t)).toBeVisible(); await noHScroll(page, false);
  });
  test("the Audit hub aggregates the verify-on-demand machinery", async ({ page }) => {
    await gotoReady(page, "/audit?tab=books"); await vis(hdg(page, "Audit"));
    for (const [n, h] of [[/Reconciliation/, "/reconciliation"], [/Journal/, "/journal"], [/Statements/, "/upload"]] as const) await att(lnk(page, n), "href", h);
    await noHScroll(page, false);
  });
  test("the merged Settings page exposes General/AI/LLM tabs", async ({ page }) => {
    await gotoReady(page, "/settings"); await vis(page.getByRole("tablist", { name: "Settings sections" }));
    for (const n of ["General", "AI", "LLM Models", "Accounts"]) await expect(page.getByRole("tab", { name: n })).toBeVisible();
    await noHScroll(page, false);
  });
});
// AC-meta.fe-ia-nav.30
