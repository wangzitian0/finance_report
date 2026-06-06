import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AdvisorBrief, safeAdvisorHref } from "@/components/advisor/AdvisorBrief";
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
    next_action_href: "/portfolio/prices/update",
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
    expect(screen.getByText("workflow.status")).toBeInTheDocument();
    expect(screen.getByText("source unavailable")).toBeInTheDocument();

    const cards = screen.getAllByTestId(/advisor-brief-card-/);
    const cardLinks = cards.map((card) => within(card).getByRole("link", { name: "Open next action" }));
    expect(cardLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/reports/package",
      "/reports",
      "/review",
      "/portfolio/prices",
      "/assets",
    ]);
    expect(safeAdvisorHref("https://evil.example/review")).toBe("/dashboard");
    expect(safeAdvisorHref("/portfolio/prices/update?source=advisor")).toBe("/portfolio/prices");
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
      expect(within(card).getAllByText("workflow.status")).toHaveLength(2);
      expect(
        consoleError.mock.calls.some((call) => call.some((arg) => String(arg).includes("same key"))),
      ).toBe(false);
    } finally {
      consoleError.mockRestore();
    }
  });
});
