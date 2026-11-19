import { expect, test } from "@playwright/test";
import { VP, att, bs1k, gotoReady, hdg, homeRoutes, installApiMocks, isFixture, noHScroll, vis, wfEvent, wfSession, wfStatus } from "./helpers";

const routes = homeRoutes({
  "/api/chat/suggestions": { suggestions: ["How is my Advisor Brief?"], structured_suggestions: [{ basis: "B", confidence_tier: "blocked", source_refs: ["workflow.status"], limitation: "L", next_action_href: "/reports/package" }, { basis: "S", confidence_tier: "stale", source_refs: ["market_data.freshness"], limitation: "L", next_action_href: "/portfolio?panel=prices" }] },
  "/api/workflow/status": wfStatus({ next_action: { type: "review_required", count: 1, href: "/review", label: "Review required" }, report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" } }),
  "/api/workflow/events": { total: 1, items: [wfEvent("e1", "u", "as")], sessions: [wfSession("as", { title: "Advisor Brief", report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" } })] },
  "/api/reports/balance-sheet*": bs1k(), "/api/reports/income-statement*": isFixture({ end_date: "2026-06-03" }),
});

test.describe("AC21.3.4 Advisor Brief responsive layout", () => {
  for (const { name, width, height } of VP) {
    test(`${name} advisor-brief desktop and mobile layouts avoid horizontal overflow`, async ({ page }) => {
      await installApiMocks(page, "advisor", routes); await gotoReady(page, "/", { width, height });
      const b = page.getByLabel("Advisor Brief"); await vis(hdg(b, "Advisor Brief"));
      for (const txt of ["Readiness blocker", "Refresh market data"]) await expect(b.getByText(txt)).toBeVisible();
      const n = b.getByRole("link", { name: "Open next action" });
      await att(n.nth(0), "href", "/reports?tab=package"); await att(n.nth(1), "href", "/portfolio?panel=prices");
      await att(b.getByRole("link", { name: "Ask about this" }).nth(0), "href", /\/chat\?prompt=/); await noHScroll(page);
    });
  }
});
// AC-advisor.fe-remainder-chat.4
