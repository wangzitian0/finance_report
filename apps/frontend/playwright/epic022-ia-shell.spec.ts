import { expect, test } from "@playwright/test";
import { expectPrimaryNav, homeRoutes, installApiMocks, gotoReady, noHScroll, vis, wfSession, wfStatus } from "./helpers";

const routes = homeRoutes({ "/api/workflow/status": wfStatus({ next_action: { type: "review_required", count: 2, href: "/review" }, event_counts: { unread: 3, action_required: 2, blocked: 1 }, active_session: wfSession("ia-shell-session", { started_at: "2026-06-04T01:00:00Z", last_event_at: "2026-06-04T02:00:00Z", source_count: 3, event_counts: { unread: 3, action_required: 2, blocked: 1 } }) }) });

test.describe("AC22.1.9 everyday-user IA shell smoke", () => {
  test.beforeEach(async ({ page }) => installApiMocks(page, "ia-shell-user", routes));
  test("desktop sidebar mirrors the five bottom-tab targets and the notification bell", async ({ page }) => {
    await gotoReady(page, "/", { width: 1440, height: 1000 });
    const nav = await expectPrimaryNav(page, "Sidebar navigation");
    await expect(page.getByRole("button", { name: /Workflow events/ })).toBeVisible();
    for (const r of [nav.getByRole("link", { name: "Journal" }), nav.getByRole("button", { name: /Advanced/ })]) await expect(r).toHaveCount(0);
    await noHScroll(page);
  });
  test("mobile shows the bottom tab bar and the bell without overflow", async ({ page }) => {
    await gotoReady(page, "/", { width: 390, height: 844 });
    await vis(page.getByRole("button", { name: /Workflow events/ }));
    await expectPrimaryNav(page, "Primary");
    await noHScroll(page);
  });
});
// AC-meta.fe-ia-nav.8
