// #2646: Home bounds its default period by the first statement, so the period of a new user has no
// coverage blocker and its "Change in period" is not the whole net worth.

import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api-client";

import { setTestUrl } from "./helpers/nextNavigation";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

/** The first day of the earliest approved statement of the #2646 review data. */
const FIRST_STATEMENT = "2026-07-01";

const balanceSheet = (asOfDate: string, totalAssets: string) => ({
  as_of_date: asOfDate,
  currency: "SGD",
  assets: [{ account_id: "a1", name: "DBS", type: "ASSET", amount: totalAssets }],
  liabilities: [{ account_id: "l1", name: "Card", type: "LIABILITY", amount: "1000" }],
  equity: [],
  total_assets: totalAssets,
  total_liabilities: "1000",
  total_equity: "0",
  equation_delta: "0",
  is_balanced: true,
});

function respond(operationId: string, request: { query?: Record<string, unknown> } = {}) {
  const query = request.query ?? {};
  switch (operationId) {
    case "list_statements_statements_get":
      return {
        items: [
          { id: "s-aug", status: "approved", period_start: "2026-08-01", original_filename: "aug.csv" },
          { id: "s-jul", status: "approved", period_start: FIRST_STATEMENT, original_filename: "jul.csv" },
          // An unapproved statement posts nothing: it does not move the first day.
          { id: "s-old", status: "parsed", period_start: "2026-01-01", original_filename: "old.csv", confidence_score: 95 },
        ],
        total: 3,
      };
    case "balance_sheet_reports_balance_sheet_get":
      // The opening balances of the first statement post on its first day.
      return query.as_of_date === FIRST_STATEMENT ? balanceSheet(FIRST_STATEMENT, "3500") : balanceSheet(String(query.as_of_date), "5000");
    case "income_statement_reports_income_statement_get":
      return { currency: "SGD", trends: [], income: [], expenses: [], total_income: "3000", total_expenses: "1500", net_income: "1500" };
    case "cash_flow_reports_cash_flow_get":
      return {
        currency: "SGD",
        operating: [],
        investing: [],
        financing: [],
        summary: { operating_activities: "1500", investing_activities: "0", financing_activities: "0", net_cash_flow: "1500", beginning_cash: "0", ending_cash: "1500" },
      };
    case "reconciliation_stats_reconciliation_stats_get":
      return { total_transactions: 5, matched_transactions: 5, unmatched_transactions: 0, pending_review: 0, auto_accepted: 5, match_rate: 100, score_distribution: {} };
    case "get_available_currencies_reports_currencies_get":
      return ["SGD"];
    case "get_base_currency_app_config_base_currency_get":
      return { base_currency: "SGD" };
    default:
      return { items: [], total: 0 };
  }
}

function requestsOf(operationId: string): Record<string, unknown>[] {
  return mockedApiOperation.mock.calls
    .filter(([id]) => id === operationId)
    .map(([, request]) => ((request ?? {}) as { query?: Record<string, unknown> }).query ?? {});
}

describe("Home period and the first statement (#2646)", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      Promise.resolve(respond(operationId, request))) as never);
    // The default 1Y period that ends on 2026-10-22 starts on 2025-11-01, before the first statement.
    setTestUrl("/?end=2026-10-22");
  });

  // AC-reporting.fe-period-cockpit.8
  it("AC-reporting.fe-period-cockpit.8 starts the Home period on the first statement and measures the change from it", async () => {
    render(<HomePage />);

    const balance = await screen.findByTestId("cockpit-card-balance-sheet");
    await waitFor(() => expect(within(balance).getByText("Change in period").nextElementSibling).toHaveTextContent("+SGD 1,500"));
    expect(within(balance).getByText("Net worth").nextElementSibling).toHaveTextContent("SGD 4,000");
    expect(within(balance).getByTestId("change-in-period-basis")).toHaveTextContent(
      "Change in period is measured from the end of Jul 1, 2026, the first day of your first statement.",
    );
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jul 1, 2026 – Oct 22, 2026");
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled();

    // Each period request uses the bounded start. No request uses the unbounded 1Y start.
    await waitFor(() => expect(requestsOf("cash_flow_reports_cash_flow_get")).toHaveLength(1));
    expect(requestsOf("income_statement_reports_income_statement_get")).toEqual([
      expect.objectContaining({ start_date: FIRST_STATEMENT, end_date: "2026-10-22" }),
    ]);
    expect(requestsOf("cash_flow_reports_cash_flow_get")).toEqual([
      expect.objectContaining({ start_date: FIRST_STATEMENT, end_date: "2026-10-22" }),
    ]);
    expect(requestsOf("balance_sheet_reports_balance_sheet_get").map((query) => query.as_of_date).sort()).toEqual([
      FIRST_STATEMENT,
      "2026-10-22",
    ]);
  });
});
