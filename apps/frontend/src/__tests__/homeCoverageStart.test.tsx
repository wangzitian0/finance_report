// #2646: Home bounds its default view by the cash coverage start (GET /reports/coverage), so the
// period of a new user has no coverage blocker and its "Change in period" is not the whole net worth.
// An explicit preset keeps its full period.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api-client";

import { setTestUrl, testUrl } from "./helpers/nextNavigation";

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

/** The cash coverage start of the #2646 review data: the opening balances of the July statement. */
const FIRST_STATEMENT = "2026-07-01";
let coverageStart: string | null = FIRST_STATEMENT;
let latestStatementEnd: string | null = null;
/** The cash account whose opening balance is on the coverage start. */
const LIMITING_ACCOUNTS = ["OCBC Bank"];

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
    case "report_coverage_reports_coverage_get":
      return {
        as_of_date: query.as_of_date,
        coverage_start: coverageStart,
        limiting_accounts: coverageStart ? LIMITING_ACCOUNTS : [],
        latest_statement_end: latestStatementEnd,
      };
    case "balance_sheet_reports_balance_sheet_get":
      // The opening balances post on the coverage start.
      return query.as_of_date === coverageStart ? balanceSheet(String(coverageStart), "3500") : balanceSheet(String(query.as_of_date), "5000");
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
    // The default 1Y period that ends on 2026-10-22 starts on 2025-11-01, before the coverage start.
    setTestUrl("/?end=2026-10-22");
    coverageStart = FIRST_STATEMENT;
    latestStatementEnd = null;
  });

  // AC-reporting.fe-period-cockpit.8
  it("AC-reporting.fe-period-cockpit.8 starts the Home period on the coverage start and measures the change from it", async () => {
    render(<HomePage />);

    const balance = await screen.findByTestId("cockpit-card-balance-sheet");
    await waitFor(() => expect(within(balance).getByText("Change in period").nextElementSibling).toHaveTextContent("+SGD 1,500"));
    expect(within(balance).getByText("Net worth").nextElementSibling).toHaveTextContent("SGD 4,000");
    expect(within(balance).getByTestId("change-in-period-basis")).toHaveTextContent(
      "Change in period is measured from the end of Jul 1, 2026, when your cash opening balances are complete.",
    );
    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jul 1, 2026 – Oct 22, 2026");
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled();
    // The note under the dimension bar names the account that sets the start, and links to the fix.
    expect(screen.getByTestId("report-coverage-note")).toHaveTextContent(
      "Starts Jul 1, 2026: OCBC Bank has no opening balance before this date. Add an opening balance",
    );
    expect(screen.getByRole("link", { name: "Add an opening balance" })).toHaveAttribute("href", "/settings?tab=accounts");
    // One coverage request, for the period end.
    expect(requestsOf("report_coverage_reports_coverage_get")).toEqual([{ as_of_date: "2026-10-22" }]);

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

  // AC-reporting.fe-period-cockpit.8
  it("AC-reporting.fe-period-cockpit.8 keeps an opening balance before the first statement in the default period", async () => {
    // A guided opening balance on 2026-01-01: the coverage start is that day, not the first statement.
    coverageStart = "2026-01-01";
    render(<HomePage />);

    await waitFor(() => expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jan 1, 2026 – Oct 22, 2026"));
    await waitFor(() => expect(requestsOf("income_statement_reports_income_statement_get")).toHaveLength(1));
    expect(requestsOf("income_statement_reports_income_statement_get")[0]).toMatchObject({ start_date: "2026-01-01" });
    await waitFor(() =>
      expect(requestsOf("balance_sheet_reports_balance_sheet_get").map((query) => query.as_of_date).sort()).toEqual(["2026-01-01", "2026-10-22"]),
    );
  });

  // AC-reporting.fe-period-cockpit.8
  it("AC-reporting.fe-period-cockpit.8 applies no bound when no cash account has an opening balance", async () => {
    coverageStart = null;
    render(<HomePage />);

    await waitFor(() => expect(screen.getByTestId("report-period-range")).toHaveTextContent("Nov 1, 2025 – Oct 22, 2026"));
    expect(screen.queryByTestId("change-in-period-basis")).toBeNull();
    expect(screen.queryByTestId("report-coverage-note")).toBeNull();
    expect(screen.getByRole("button", { name: "Previous period" })).toBeEnabled();
  });

  // AC-reporting.fe-period-cockpit.10
  it("AC-reporting.fe-period-cockpit.10 shows an explicit 1Y in full and bounds All to coverage start", async () => {
    mockedApiOperation.mockClear();
    setTestUrl("/?period=1Y&end=2026-10-22");
    const oneYear = render(<HomePage />);

    expect(screen.getByTestId("report-period-range")).toHaveTextContent("Nov 1, 2025 – Oct 22, 2026");
    await waitFor(() => expect(requestsOf("income_statement_reports_income_statement_get")).toHaveLength(1));
    expect(requestsOf("income_statement_reports_income_statement_get")[0]).toMatchObject({ start_date: "2025-11-01", end_date: "2026-10-22" });
    await waitFor(() => expect(requestsOf("cash_flow_reports_cash_flow_get")).toHaveLength(1));
    expect(requestsOf("cash_flow_reports_cash_flow_get")[0]).toMatchObject({ start_date: "2025-11-01" });
    expect(screen.getByRole("button", { name: "Previous period" })).toHaveProperty("disabled", false);
    expect(screen.queryByTestId("report-coverage-note")).toBeNull();
    expect(screen.queryByTestId("change-in-period-basis")).toBeNull();
    // An explicit 1Y preset does not read the coverage start.
    expect(requestsOf("report_coverage_reports_coverage_get")).toEqual([]);
    oneYear.unmount();

    mockedApiOperation.mockClear();
    setTestUrl("/?period=All&end=2026-10-22");
    const allBounded = render(<HomePage />);

    await waitFor(() => expect(screen.getByTestId("report-period-range")).toHaveTextContent("Jul 1, 2026 – Oct 22, 2026"));
    await waitFor(() => expect(requestsOf("income_statement_reports_income_statement_get")).toHaveLength(1));
    expect(requestsOf("income_statement_reports_income_statement_get")[0]).toMatchObject({ start_date: FIRST_STATEMENT, end_date: "2026-10-22" });
    await waitFor(() => expect(requestsOf("cash_flow_reports_cash_flow_get")).toHaveLength(1));
    expect(requestsOf("cash_flow_reports_cash_flow_get")[0]).toMatchObject({ start_date: FIRST_STATEMENT });
    expect(screen.getByRole("button", { name: "Previous period" })).toBeDisabled();
    expect(requestsOf("report_coverage_reports_coverage_get")).toEqual([{ as_of_date: "2026-10-22" }]);
    allBounded.unmount();
  });

  // AC-reporting.2726.2
  it("AC-reporting.2726.2 shows a one-click banner jumping to the latest statement period when statements precede the default 1Y window", async () => {
    coverageStart = "2025-01-01";
    latestStatementEnd = "2025-03-31";
    render(<HomePage />);

    const banner = await screen.findByTestId("report-latest-statement-banner");
    expect(banner).toHaveTextContent("Latest statement ends Mar 31, 2025, before this period.");
    fireEvent.click(within(banner).getByRole("button", { name: /Jump to Mar 31, 2025/i }));
    expect(testUrl()).toBe("/?end=2025-03-31");
  });
});
