import { describe, expect, it } from "vitest";

import {
  DEFAULT_ROUTE_ICON,
  advancedNavItems,
  getRouteConfig,
  primaryWorkflowNavItems,
} from "@/components/navigation";

describe("navigation metadata", () => {
  it("AC19.6.2 AC19.8.5 exposes primary workflow navigation separately from advanced drill-downs", () => {
    expect(primaryWorkflowNavItems.map((item) => item.label)).toEqual([
      "Upload Pipeline",
      "Reports",
      "AI",
    ]);
    expect(primaryWorkflowNavItems.map((item) => item.href)).toEqual([
      "/dashboard",
      "/reports",
      "/chat",
    ]);
    expect(advancedNavItems.map((item) => item.label)).toEqual([
      "Events",
      "Portfolio",
      "Statements",
      "Review",
      "Accounts",
      "Journal",
      "Reconciliation",
      "Processing",
      "AI Settings",
    ]);
    expect(advancedNavItems.find((item) => item.label === "AI Settings")?.href).toBe("/settings/ai");
  });

  it("AC16.19.4 AC19.6.6 resolves exact, parent, and advanced deep-link route labels", () => {
    expect(getRouteConfig("/reports/balance-sheet").label).toBe("Balance Sheet");
    expect(getRouteConfig("/reports/balance-sheet/detail").label).toBe("Balance Sheet");
    expect(getRouteConfig("/review/run/123").label).toBe("Review");
    expect(getRouteConfig("/reconciliation/unmatched").label).toBe("Unmatched");
    expect(getRouteConfig("/processing").label).toBe("Processing");
    expect(getRouteConfig("/chat").label).toBe("AI");
    expect(getRouteConfig("/settings/ai").label).toBe("AI Settings");
    expect(getRouteConfig("/custom-report_page").label).toBe("Custom Report Page");
    expect(getRouteConfig("/").Icon).toBe(DEFAULT_ROUTE_ICON);
  });
});
