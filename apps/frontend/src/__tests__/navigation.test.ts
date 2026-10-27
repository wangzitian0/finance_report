import { describe, expect, it } from "vitest";

import {
  ADD_ACTION,
  APP_ROUTES,
  DEFAULT_ROUTE_ICON,
  ROUTE_CONFIG,
  advancedItems,
  auditHubItems,
  bottomTabItems,
  getRouteConfig,
  isActive,
  moreItems,
} from "@/components/navigation";
import routeMapJson from "@/lib/route-map.json";

const ACCOUNTING_JARGON_HREFS = [
  "/journal",
  "/reconciliation",
  "/settings?tab=accounts",
  "/statements",
  "/settings",
];

describe("navigation metadata", () => {
  // AC-meta.fe-ia-nav.1 / AC-meta.fe-ia-nav.6 / AC-meta.fe-ia-nav.9 / AC-meta.fe-ia-nav.25
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

  // AC-meta.fe-ia-nav.27
  it("AC22.21.3 folds the accounting machinery into the /audit hub, out of navigation", () => {
    const auditHrefs = auditHubItems.map((item) => item.href);
    expect(auditHrefs).toEqual(
      expect.arrayContaining(["/reconciliation", "/journal", "/upload"]),
    );
    // None of these machinery routes is reachable as a bottom tab.
    const tabHrefs = bottomTabItems.map((item) => item.href);
    for (const href of auditHrefs) {
      expect(tabHrefs).not.toContain(href);
    }
  });

  // AC-meta.fe-ia-nav.29
  it("AC22.21.5 routes low-frequency destinations through the /more overflow", () => {
    const moreHrefs = moreItems.map((item) => item.href);
    expect(moreHrefs).toEqual(["/portfolio", "/reports", "/settings"]);
    // Accounts is the genuine power escape hatch under Advanced, not a tab.
    expect(advancedItems.map((item) => item.href)).toContain("/settings?tab=accounts");
  });

  // AC-meta.fe-ia-nav.5
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
    expect(getRouteConfig("/reports").label).toBe("Reports");
    expect(getRouteConfig("/reports/unknown-subpath").label).toBe("Reports");
    expect(getRouteConfig("").label).toBe("Page");
    expect(getRouteConfig("/chat").label).toBe("Chat");
    expect(getRouteConfig("/audit").label).toBe("Audit");
    expect(getRouteConfig("/more").label).toBe("More");
    expect(getRouteConfig("/settings").label).toBe("Settings");
    expect(getRouteConfig("/portfolio/AAPL").label).toBe("Portfolio");
    expect(getRouteConfig("/").label).toBe("Home");
    expect(getRouteConfig("/upload").label).toBe("Upload");
    expect(getRouteConfig("/custom-report_page").label).toBe("Custom Report Page");
    expect(getRouteConfig("/totally-unknown-xyz").Icon).toBe(DEFAULT_ROUTE_ICON);
  });

  // AC-meta.fe-ia-nav.20
  it("AC22.18.1 keeps every redirect route of the route map out of ROUTE_CONFIG so no stale label leaks", () => {
    const redirects = routeMapJson.routes.filter((r) => r.state === "redirect").map((r) => r.path);
    expect(redirects).toContain("/events");
    expect(redirects).toContain("/assets");
    for (const retired of redirects) {
      expect(ROUTE_CONFIG[retired], `${retired} must not have a ROUTE_CONFIG entry`).toBeUndefined();
    }
    expect(getRouteConfig("/events").Icon).toBe(DEFAULT_ROUTE_ICON);
    expect(getRouteConfig("/events").label).toBe("Events");
  });

  // AC-meta.fe-ia-nav.36
  it("AC-meta.fe-ia-nav.36 labels every dynamic target page of the route map by pattern, not by its parameter", () => {
    const dynamicTargets = routeMapJson.routes
      .filter((r) => r.state === "target" && r.path.includes("["))
      .map((r) => r.path);
    expect(dynamicTargets).toContain("/statements/[id]");

    const uuid = "3f2b8c1e-9d4a-4e57-8a60-1c2d3e4f5a6b";
    for (const target of dynamicTargets) {
      const entry = ROUTE_CONFIG[target];
      expect(entry, `${target} needs a ROUTE_CONFIG entry`).toBeDefined();
      const concrete = target.replace(/\[[^\]]+\]/g, uuid);
      expect(getRouteConfig(concrete), `${concrete} must resolve to ${target}`).toBe(entry);
      expect(getRouteConfig(concrete).label).not.toContain(uuid);
    }
    expect(getRouteConfig(`/statements/${uuid}`).label).toBe("Statement");
    // A pattern matches one segment only: a deeper path still resolves through its parents.
    expect(getRouteConfig(`/statements/${uuid}/extra`).label).not.toBe("Statement");
  });

  // Single-homed from Sidebar.tsx/BottomTabBar.tsx byte-identical duplicates (#1868 S5).
  it("isActive matches home exactly and other routes exactly or by path prefix", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/reports", "/")).toBe(false);
    expect(isActive("/reports", "/reports")).toBe(true);
    expect(isActive("/portfolio/prices", "/portfolio")).toBe(true);
    expect(isActive("/reportsomething", "/reports")).toBe(false);
    expect(isActive("/journal", "/reports")).toBe(false);
  });

  it("exposes APP_ROUTES SSOT constants covering all core navigation surfaces", () => {
    // Assert every declared APP_ROUTES constant is represented in ROUTE_CONFIG.
    // A route with a query (a tab or a drawer) uses the entry of its page path.
    for (const [key, route] of Object.entries(APP_ROUTES)) {
      expect(
        ROUTE_CONFIG[route.split("?")[0]],
        `Route ${key} (${route}) must have a matching ROUTE_CONFIG entry`,
      ).toBeDefined();
    }

    expect(APP_ROUTES.HOME).toBe("/");
    expect(APP_ROUTES.UPLOAD).toBe("/upload");
    expect(APP_ROUTES.AUDIT).toBe("/audit");
    expect(APP_ROUTES.CHAT).toBe("/chat");
    expect(APP_ROUTES.RECONCILIATION_REVIEW_QUEUE).toBe("/reconciliation?tab=review-queue");
  });
});
