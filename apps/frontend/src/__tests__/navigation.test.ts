import { describe, expect, it } from "vitest";

import {
  ADD_ACTION,
  DEFAULT_ROUTE_ICON,
  ROUTE_CONFIG,
  advancedItems,
  auditHubItems,
  bottomTabItems,
  getRouteConfig,
  moreItems,
} from "@/components/navigation";

const ACCOUNTING_JARGON_HREFS = [
  "/journal",
  "/reconciliation",
  "/accounts",
  "/statements",
  "/settings",
  "/processing",
  "/confidence",
];

describe("navigation metadata", () => {
  it("AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)", () => {
    expect(bottomTabItems.map((item) => item.label)).toEqual([
      "Home",
      "Chat",
      "Audit",
      "More",
    ]);
    expect(bottomTabItems.map((item) => item.href)).toEqual([
      "/",
      "/chat",
      "/audit",
      "/more",
    ]);

    // Add is the center action — an action that opens a sheet, not a route.
    expect(ADD_ACTION.label).toBe("Add");

    // AC22.1.1: no accounting-jargon route or settings page is a bottom tab.
    const tabHrefs = bottomTabItems.map((item) => item.href);
    for (const jargonHref of ACCOUNTING_JARGON_HREFS) {
      expect(tabHrefs).not.toContain(jargonHref);
    }

    // The four bottom tabs use distinct icons.
    const icons = bottomTabItems.map((item) => item.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it("AC22.21.3 folds the accounting machinery into the /audit hub, out of navigation", () => {
    const auditHrefs = auditHubItems.map((item) => item.href);
    expect(auditHrefs).toEqual(
      expect.arrayContaining(["/confidence", "/reconciliation", "/journal", "/processing"]),
    );
    // None of these machinery routes is reachable as a bottom tab.
    const tabHrefs = bottomTabItems.map((item) => item.href);
    for (const href of auditHrefs) {
      expect(tabHrefs).not.toContain(href);
    }
  });

  it("AC22.21.5 routes low-frequency destinations through the /more overflow", () => {
    const moreHrefs = moreItems.map((item) => item.href);
    expect(moreHrefs).toEqual(expect.arrayContaining(["/portfolio", "/settings"]));
    // Accounts is the genuine power escape hatch under Advanced, not a tab.
    expect(advancedItems.map((item) => item.href)).toContain("/accounts");
  });

  it("AC22.1.6 lists Portfolio exactly once across the navigation model", () => {
    const portfolioEntries = [
      ...bottomTabItems,
      ...auditHubItems,
      ...moreItems,
      ...advancedItems,
    ].filter((item) => item.label === "Portfolio");
    expect(portfolioEntries).toHaveLength(1);
    expect(portfolioEntries[0].href).toBe("/portfolio");
  });

  it("AC16.19.4 AC19.6.6 resolves exact, parent, advanced, and home route labels", () => {
    expect(getRouteConfig("/reports/balance-sheet").label).toBe("Balance Sheet");
    expect(getRouteConfig("/reports/balance-sheet/detail").label).toBe("Balance Sheet");
    expect(getRouteConfig("/review/run/123").label).toBe("Review");
    expect(getRouteConfig("/reconciliation/unmatched").label).toBe("Unmatched");
    expect(getRouteConfig("/processing").label).toBe("Processing");
    expect(getRouteConfig("/chat").label).toBe("Chat");
    expect(getRouteConfig("/audit").label).toBe("Audit");
    expect(getRouteConfig("/more").label).toBe("More");
    expect(getRouteConfig("/settings").label).toBe("Settings");
    expect(getRouteConfig("/settings/ai").label).toBe("AI Settings");
    expect(getRouteConfig("/settings/llm").label).toBe("LLM Models");
    expect(getRouteConfig("/").label).toBe("Home");
    expect(getRouteConfig("/upload").label).toBe("Upload");
    expect(getRouteConfig("/notifications").label).toBe("Notifications");
    expect(getRouteConfig("/custom-report_page").label).toBe("Custom Report Page");
    expect(getRouteConfig("/totally-unknown-xyz").Icon).toBe(DEFAULT_ROUTE_ICON);
  });

  it("AC22.18.1 drops the legacy /events alias so /notifications is the one canonical label", () => {
    expect(ROUTE_CONFIG["/events"]).toBeUndefined();
    expect(getRouteConfig("/events").label).toBe("Events");
    expect(getRouteConfig("/notifications").label).toBe("Notifications");
  });
});
