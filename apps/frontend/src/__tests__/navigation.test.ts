import { describe, expect, it } from "vitest";

import {
  DEFAULT_ROUTE_ICON,
  advancedNavItems,
  getRouteConfig,
  primaryWorkflowNavItems,
} from "@/components/navigation";

const ACCOUNTING_JARGON_HREFS = ["/journal", "/reconciliation", "/accounts", "/statements"];

describe("navigation metadata", () => {
  it("AC19.6.2 AC19.8.5 AC22.1.1 AC22.2.4 exposes exactly three everyday peers and folds the rest into advanced", () => {
    expect(primaryWorkflowNavItems.map((item) => item.label)).toEqual([
      "Upload",
      "Reports",
      "Chat",
    ]);
    expect(primaryWorkflowNavItems.map((item) => item.href)).toEqual([
      "/upload",
      "/reports",
      "/chat",
    ]);

    // AC22.1.1: no accounting-jargon route is a top-level peer.
    const primaryHrefs = primaryWorkflowNavItems.map((item) => item.href);
    for (const jargonHref of ACCOUNTING_JARGON_HREFS) {
      expect(primaryHrefs).not.toContain(jargonHref);
    }

    expect(advancedNavItems.map((item) => item.label)).toEqual([
      "Portfolio",
      "Accounts",
      "Journal",
      "Reconciliation",
      "Processing",
      "Confidence Trend",
      "AI Settings",
    ]);
    expect(advancedNavItems.find((item) => item.label === "AI Settings")?.href).toBe("/settings/ai");

    // AC22.1.4: the legacy "Upload Pipeline" label is gone from the nav model.
    const allLabels = [...primaryWorkflowNavItems, ...advancedNavItems].map((item) => item.label);
    expect(allLabels).not.toContain("Upload Pipeline");
    // Events lives in the header bell, not the sidebar nav.
    expect(allLabels).not.toContain("Events");
    // AC22.2.4: the standalone Review Queue is folded into the notification center.
    expect(allLabels).not.toContain("Review");
  });

  it("AC22.1.6 lists Portfolio exactly once across the navigation model", () => {
    const portfolioEntries = [...primaryWorkflowNavItems, ...advancedNavItems].filter(
      (item) => item.label === "Portfolio",
    );
    expect(portfolioEntries).toHaveLength(1);
    expect(portfolioEntries[0].href).toBe("/portfolio");
  });

  it("AC22.1.7 gives Chat and AI Settings distinct icons", () => {
    const chat = primaryWorkflowNavItems.find((item) => item.label === "Chat");
    const aiSettings = advancedNavItems.find((item) => item.label === "AI Settings");
    expect(chat).toBeDefined();
    expect(aiSettings).toBeDefined();
    expect(chat?.icon).not.toBe(aiSettings?.icon);
  });

  it("AC16.19.4 AC19.6.6 resolves exact, parent, advanced, and home route labels", () => {
    expect(getRouteConfig("/reports/balance-sheet").label).toBe("Balance Sheet");
    expect(getRouteConfig("/reports/balance-sheet/detail").label).toBe("Balance Sheet");
    expect(getRouteConfig("/review/run/123").label).toBe("Review");
    expect(getRouteConfig("/reconciliation/unmatched").label).toBe("Unmatched");
    expect(getRouteConfig("/processing").label).toBe("Processing");
    expect(getRouteConfig("/chat").label).toBe("Chat");
    expect(getRouteConfig("/settings/ai").label).toBe("AI Settings");
    expect(getRouteConfig("/").label).toBe("Home");
    expect(getRouteConfig("/upload").label).toBe("Upload");
    expect(getRouteConfig("/notifications").label).toBe("Notifications");
    expect(getRouteConfig("/custom-report_page").label).toBe("Custom Report Page");
    expect(getRouteConfig("/totally-unknown-xyz").Icon).toBe(DEFAULT_ROUTE_ICON);
  });
});
