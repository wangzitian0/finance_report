import { expect, test } from "@playwright/test";
import { expectPrimaryNav, gotoReady, homeRoutes, installApiMocks, noHScroll, wfSession, wfStatus } from "./helpers";

const routes = homeRoutes({ "/api/workflow/status": wfStatus({ next_action: { type: "review_required", count: 2, href: "/review" }, event_counts: { unread: 4, action_required: 2, blocked: 1 }, active_session: wfSession("workflow-session", { started_at: "2026-06-04T01:00:00Z", last_event_at: "2026-06-04T02:00:00Z", source_count: 4, event_counts: { unread: 4, action_required: 2, blocked: 1 } }) }) });

test.describe("AC19.6.7 workflow navigation folding", () => {
  test.beforeEach(async ({ page }) => installApiMocks(page, "workflow-navigation-user", routes));
  for (const [label, w, h, navName, gone] of [
    ["desktop sidebar exposes the five bottom-tab targets", 1440, 1000, "Sidebar navigation", true],
    ["mobile exposes the bottom tab bar", 390, 844, "Primary", false],
  ] as const) {
    test(label, async ({ page }) => {
      await gotoReady(page, "/", { width: w, height: h });
      const nav = await expectPrimaryNav(page, navName, true);
      if (gone) { await expect(nav.getByRole("button", { name: /Advanced/ })).toHaveCount(0); await expect(nav.getByRole("link", { name: "Reconciliation" })).toHaveCount(0); }
      await noHScroll(page);
    });
  }
});
