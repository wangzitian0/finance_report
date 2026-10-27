import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AdvisorBrief, safeAdvisorHref } from "@/components/advisor/AdvisorBrief";
import routeMap from "@/lib/route-map.json";
import type { AdvisorSuggestion } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const advisorSuggestions: AdvisorSuggestion[] = [
  {
    basis: "Report package is blocked by one review-required item.",
    confidence_tier: "blocked",
    source_refs: ["workflow.status", "report_package.readiness"],
    limitation: "Do not rely on the final report until review is complete.",
    next_action_href: "/reports/package",
  },
  {
    basis: "Balance sheet and income statement are ready from posted ledger entries.",
    confidence_tier: "deterministic",
    source_refs: ["reports.balance_sheet", "reports.income_statement"],
    limitation: "This only reflects posted and reconciled ledger data.",
    next_action_href: "/reports",
  },
  {
    basis: "Two reconciliation items still need source confirmation.",
    confidence_tier: "review_required",
    source_refs: ["reconciliation.stats"],
    limitation: "Unreviewed items can still change report totals.",
    next_action_href: "/review",
  },
  {
    basis: "Market prices are stale for one portfolio holding.",
    confidence_tier: "stale",
    source_refs: ["market_data.freshness"],
    limitation: "Portfolio value may be outdated until prices refresh.",
    next_action_href: "/portfolio?panel=prices",
  },
  {
    basis: "Manual evidence exists for one asset but it is not yet trusted.",
    confidence_tier: "unsupported",
    source_refs: [],
    limitation: "Manual evidence needs an internal support path before it can drive report conclusions.",
    next_action_href: "/assets?filter=manual",
  },
];

describe("AdvisorBrief", () => {
  // AC-advisor.fe-remainder-chat.2
  it("AC21.3.2 test_AC21_3_2_advisor_brief_renders_structured_cards_and_safe_routes", () => {
    render(<AdvisorBrief suggestions={advisorSuggestions} />);

    expect(screen.getByLabelText("Advisor Brief")).toBeInTheDocument();
    expect(screen.getByText("Readiness blocker")).toBeInTheDocument();
    expect(screen.getByText("Ready facts")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("Refresh market data")).toBeInTheDocument();
    expect(screen.getByText("Advisor signal")).toBeInTheDocument();
    expect(screen.getByText("Report package is blocked by one review-required item.")).toBeInTheDocument();
    expect(screen.getByText("Do not rely on the final report until review is complete.")).toBeInTheDocument();
    expect(screen.getByText("Workflow Status")).toBeInTheDocument();
    expect(screen.getByText("source unavailable")).toBeInTheDocument();

    const cards = screen.getAllByTestId(/advisor-brief-card-/);
    const cardLinks = cards.map((card) => within(card).getByRole("link", { name: "Open next action" }));
    // The backend still names the old report routes; the brief links to their /reports tabs.
    expect(cardLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/reports?tab=package",
      "/reports",
      "/upload",
      "/portfolio?panel=prices",
      "/portfolio",
    ]);
    expect(safeAdvisorHref("https://evil.example/review")).toBe("/");
    expect(safeAdvisorHref("//evil.example/reports")).toBe("/");
    expect(safeAdvisorHref("/ping-pong")).toBe("/");
    expect(safeAdvisorHref("/portfolio/AAPL")).toBe("/");
    expect(safeAdvisorHref("/portfolio?panel=prices&source=advisor")).toBe("/portfolio?panel=prices");
    expect(safeAdvisorHref("/portfolio?panel=evil")).toBe("/portfolio");
    expect(safeAdvisorHref("/reconciliation?tab=review-queue")).toBe("/reconciliation?tab=review-queue");
    expect(safeAdvisorHref("/reports/")).toBe("/reports");
    expect(safeAdvisorHref("/events#top")).toBe("/upload");
    expect(within(cards[0]).getByRole("link", { name: "Ask about this" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt="),
    );
  });

  it("AC21.3.2 renders duplicate source refs without duplicate React keys", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    try {
      render(
        <AdvisorBrief
          suggestions={[
            {
              basis: "Two readiness blockers share the same source.",
              confidence_tier: "blocked",
              source_refs: ["workflow.status", "workflow.status"],
              limitation: "Resolve both blockers before using the report.",
              next_action_href: "/reports/package",
            },
          ]}
        />,
      );

      const card = screen.getByTestId("advisor-brief-card-0");
      expect(within(card).getAllByText("Workflow Status")).toHaveLength(2);
      expect(
        consoleError.mock.calls.some((call) => call.some((arg) => String(arg).includes("same key"))),
      ).toBe(false);
    } finally {
      consoleError.mockRestore();
    }
  });
});

describe("safeAdvisorHref follows route-map.json", () => {
  const redirects = routeMap.routes.filter(
    (route) => route.state === "redirect" && !route.path.includes("[") && !route.into?.includes(":"),
  );

  it("sends every static redirect of the route map to its target", () => {
    expect(redirects.length).toBeGreaterThan(20);
    for (const route of redirects) {
      expect(safeAdvisorHref(route.path), route.path).toBe(route.into);
    }
  });

  it("keeps every target page of the route map", () => {
    const targets = routeMap.routes.filter((route) => route.state === "target" && !route.path.includes("["));
    expect(targets.length).toBeGreaterThan(5);
    for (const route of targets) {
      expect(safeAdvisorHref(route.path), route.path).toBe(route.path);
    }
  });
});
