import { describe, expect, it } from "vitest";

import { DEFAULT_ROUTE_ICON, getRouteConfig, primaryNavItems } from "@/components/navigation";

describe("navigation metadata", () => {
  it("AC16.23.5 exposes the full primary navigation set for mobile and desktop", () => {
    expect(primaryNavItems.map((item) => item.label)).toEqual([
      "Dashboard",
      "Events",
      "Accounts",
      "Journal",
      "Statements",
      "Review",
      "Portfolio",
      "Reports",
      "Reconciliation",
      "Processing",
      "AI Advisor",
    ]);
  });

  it("AC16.19.4 resolves exact, parent, and derived route labels", () => {
    expect(getRouteConfig("/reports/balance-sheet").label).toBe("Balance Sheet");
    expect(getRouteConfig("/reports/balance-sheet/detail").label).toBe("Balance Sheet");
    expect(getRouteConfig("/custom-report_page").label).toBe("Custom Report Page");
    expect(getRouteConfig("/").Icon).toBe(DEFAULT_ROUTE_ICON);
  });
});
