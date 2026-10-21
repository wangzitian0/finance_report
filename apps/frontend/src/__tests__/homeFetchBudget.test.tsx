// #2583 S4 — Home fetch budget.
//
// The Home route used to fire ten raw `apiOperation` calls in one Promise.all with
// no cache. Each visit and each toggle ran all of them again. These tests count
// the calls per operation and request, through the same `apiOperation` mock the
// other Home tests use.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api-client";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/charts/BarChart", () => ({ BarChart: () => <div>BarChartMock</div> }));
vi.mock("@/components/charts/PieChart", () => ({ PieChart: () => <div>PieChartMock</div> }));
vi.mock("@/components/charts/TrendChart", () => ({ TrendChart: () => <div>TrendChartMock</div> }));
vi.mock("@/components/charts/NetWorthTimeSeriesChart", () => ({
  NetWorthTimeSeriesChart: () => <div>NetWorthTimeSeriesMock</div>,
}));
vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

// Operations that only feed cards inside the opt-in analytics panel.
const ANALYTICS_ONLY_OPERATIONS = [
  "get_annualized_income_income_annualized_get",
  "list_restricted_holdings_assets_restricted_get",
  "list_unmatched_reconciliation_unmatched_get",
  "account_trend_reports_trend_get",
];

const BALANCE = {
  assets: [{ account_id: "a1", name: "Cash", amount: "5000" }],
  liabilities: [],
  equity: [],
  total_assets: "5000",
  total_liabilities: "1000",
  total_equity: "4000",
  equation_delta: "0",
  currency: "USD",
  as_of_date: "2026-02-01",
  is_balanced: true,
};

function respond(operationId: string, request?: { query?: Record<string, unknown> }) {
  switch (operationId) {
    case "balance_sheet_reports_balance_sheet_get":
      return request?.query?.include_restricted
        ? { ...BALANCE, total_assets: "17500", total_equity: "16500" }
        : BALANCE;
    case "income_statement_reports_income_statement_get":
      return {
        currency: "USD",
        trends: [{ period_start: "2026-01-01", total_income: "3500", total_expenses: "1200", net_income: "2300" }],
        income: [],
        expenses: [],
        total_income: "3500",
        total_expenses: "1200",
        net_income: "2300",
      };
    case "get_annualized_income_income_annualized_get":
      return { annualized_salary: "1", annualized_bonus: "0", annualized_dividend: "0", annualized_total: "1", currency: "USD", as_of: "2026-05-20" };
    case "list_restricted_holdings_assets_restricted_get":
      return [];
    case "reconciliation_stats_reconciliation_stats_get":
      return { total_transactions: 20, matched_transactions: 16, unmatched_transactions: 4, pending_review: 2, auto_accepted: 4, match_rate: 80, score_distribution: {} };
    case "list_unmatched_reconciliation_unmatched_get":
      return { items: [], total: 0 };
    case "list_journal_entries_journal_entries_get":
      return { items: [{ id: "j1", memo: "Rent", entry_date: "2026-01-05", status: "posted" }], total: 1 };
    case "list_accounts_accounts_get":
      return { items: [{ id: "a1" }], total: 1 };
    case "list_statements_statements_get":
      return { items: [{ id: "s1", status: "approved" }], total: 1 };
    case "list_processing_pending_accounts_processing_pending_get":
      return { items: [], total: 0 };
    case "suggestions_chat_suggestions_get":
      return { suggestions: [], structured_suggestions: [] };
    case "account_trend_reports_trend_get":
      return { points: [{ period_start: "2026-01-01", amount: "5000" }] };
    case "get_workflow_status_endpoint_workflow_status_get":
      return {
        primary_state: "ready",
        next_action: { type: "open_report", count: 0, href: "/reports", label: "Open reports", summary: "Reports are ready." },
        report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
        event_counts: { unread: 0, action_required: 0, blocked: 0 },
      };
    case "list_workflow_events_endpoint_workflow_events_get":
      return { total: 0, items: [], sessions: [] };
    default:
      return null;
  }
}

function requestKey(operationId: string, request: unknown): string {
  const { signal: _signal, ...rest } = (request ?? {}) as Record<string, unknown>;
  return `${operationId} ${JSON.stringify(rest)}`;
}

function callKeys(): string[] {
  return mockedApiOperation.mock.calls.map(([operationId, request]) => requestKey(String(operationId), request));
}

function countByKey(keys: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const key of keys) counts.set(key, (counts.get(key) ?? 0) + 1);
  return counts;
}

function operationIdOf(key: string): string {
  return key.split(" ")[0];
}

function createClient() {
  // Same defaults as app/providers.tsx.
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 60_000, retry: false, refetchOnWindowFocus: false } },
  });
}

function renderHome(client: QueryClient) {
  return render(<HomePage />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

async function settleClosedHome() {
  await waitFor(() => expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveTextContent("Position $4,000"));
  await waitFor(() => expect(screen.queryByLabelText("Dashboard analytics loading")).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByText("Upload to report")).toBeInTheDocument());
}

describe("Home fetch budget (#2583 S4)", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      Promise.resolve(respond(operationId, request))) as never);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 cold mount issues each request at most once and defers the analytics-only requests", async () => {
    renderHome(createClient());
    await settleClosedHome();

    const closed = countByKey(callKeys());
    const repeated = [...closed].filter(([, count]) => count > 1);
    expect(repeated, `requests issued more than once: ${JSON.stringify(repeated)}`).toEqual([]);

    // The analytics panel is closed: its four card feeds, the recent entries and the trend must not run yet.
    const closedOperations = new Set([...closed.keys()].map(operationIdOf));
    for (const operationId of ANALYTICS_ONLY_OPERATIONS) {
      expect(closedOperations.has(operationId), `${operationId} ran while the analytics panel was closed`).toBe(false);
    }
    expect([...closed.keys()].filter((key) => key.startsWith("list_journal_entries_journal_entries_get"))).toEqual([
      'list_journal_entries_journal_entries_get {"query":{"status_filter":"posted","limit":1}}',
    ]);
    expect(closed.size).toBeLessThanOrEqual(10);

    fireEvent.click(screen.getByRole("button", { name: /Show analytics/i }));
    await waitFor(() => expect(screen.getByText("BarChartMock")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("TrendChartMock")).toBeInTheDocument());

    const opened = countByKey(callKeys());
    expect([...opened].filter(([, count]) => count > 1)).toEqual([]);
    for (const operationId of ANALYTICS_ONLY_OPERATIONS) {
      expect(new Set([...opened.keys()].map(operationIdOf)).has(operationId), `${operationId} never ran`).toBe(true);
    }
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 a second visit inside the stale time issues no request for cached data", async () => {
    const client = createClient();
    const first = renderHome(client);
    await settleClosedHome();
    first.unmount();
    mockedApiOperation.mockClear();

    renderHome(client);
    await settleClosedHome();

    const homeOperations = [
      "balance_sheet_reports_balance_sheet_get",
      "income_statement_reports_income_statement_get",
      "reconciliation_stats_reconciliation_stats_get",
      "list_accounts_accounts_get",
      "list_statements_statements_get",
      "list_journal_entries_journal_entries_get",
      "list_processing_pending_accounts_processing_pending_get",
      "suggestions_chat_suggestions_get",
    ];
    const secondVisit = callKeys().filter((key) => homeOperations.includes(operationIdOf(key)));
    expect(secondVisit).toEqual([]);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 toggling restricted holdings refetches only the balance sheet", async () => {
    renderHome(createClient());
    await settleClosedHome();
    mockedApiOperation.mockClear();

    fireEvent.click(screen.getByLabelText("Include restricted holdings"));
    await waitFor(() => expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveTextContent("Position $16,500"));

    expect(callKeys()).toEqual([
      'balance_sheet_reports_balance_sheet_get {"query":{"include_restricted":true}}',
    ]);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 changing the period refetches only the income statement", async () => {
    renderHome(createClient());
    await settleClosedHome();
    mockedApiOperation.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Period 1M" }));
    await waitFor(() => expect(callKeys().length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByRole("button", { name: "Period 1M" })).toHaveAttribute("aria-pressed", "true"));

    expect(callKeys().map(operationIdOf)).toEqual(["income_statement_reports_income_statement_get"]);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 renders the cockpit from its own data while a slower request is still pending", async () => {
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      operationId === "list_accounts_accounts_get"
        ? new Promise(() => {})
        : Promise.resolve(respond(operationId, request))) as never);

    renderHome(createClient());

    await waitFor(() => expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveTextContent("Position $4,000"));
    expect(screen.getByTestId("cockpit-card-income-statement")).toHaveTextContent("Net $2,300");
    expect(screen.getByLabelText("Dashboard analytics loading")).toBeInTheDocument();
  });

  // AC-reporting.fe-fetch-budget.2
  it("AC-reporting.fe-fetch-budget.2 the advisor suggestions do not block the cockpit and stay cached for five minutes", async () => {
    let resolveSuggestions: (value: unknown) => void = () => {};
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      operationId === "suggestions_chat_suggestions_get"
        ? new Promise((resolve) => {
            resolveSuggestions = resolve;
          })
        : Promise.resolve(respond(operationId, request))) as never);

    const client = createClient();
    renderHome(client);
    await settleClosedHome();

    const suggestionKeys = client
      .getQueryCache()
      .getAll()
      .filter((query) => JSON.stringify(query.queryKey).includes("suggestions"));
    expect(suggestionKeys).toHaveLength(1);
    const staleTime = suggestionKeys[0].observers[0]?.options.staleTime;
    expect(staleTime).toBeGreaterThanOrEqual(5 * 60 * 1000);
    resolveSuggestions({ suggestions: [], structured_suggestions: [] });
  });
});
