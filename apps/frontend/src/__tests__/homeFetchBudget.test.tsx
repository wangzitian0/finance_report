// #2583 S4 — Home fetch budget, for the period-driven Home of #2621 LC.
//
// These tests count the calls per operation and request, through the same `apiOperation`
// mock the other Home tests use.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** The statement operations of one period: the balance sheet (at the end and the opening date), the income statement and the cash flow. */
const STATEMENT_OPERATIONS = [
  "balance_sheet_reports_balance_sheet_get",
  "income_statement_reports_income_statement_get",
  "cash_flow_reports_cash_flow_get",
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
      // The default scope includes restricted holdings (#2645). The liquid scope excludes 2,500 of them.
      return request?.query?.include_restricted === false ? { ...BALANCE, total_assets: "2500", total_equity: "1500" } : BALANCE;
    case "income_statement_reports_income_statement_get":
      return { currency: "USD", trends: [], income: [], expenses: [], total_income: "3500", total_expenses: "1200", net_income: "2300" };
    case "cash_flow_reports_cash_flow_get":
      return {
        currency: "USD",
        operating: [],
        investing: [],
        financing: [],
        summary: { operating_activities: "2300", investing_activities: "0", financing_activities: "0", net_cash_flow: "2300", beginning_cash: "0", ending_cash: "2300" },
      };
    case "reconciliation_stats_reconciliation_stats_get":
      return { total_transactions: 20, matched_transactions: 16, unmatched_transactions: 4, pending_review: 2, auto_accepted: 4, match_rate: 80, score_distribution: {} };
    case "list_statements_statements_get":
      return { items: [{ id: "s1", status: "approved" }], total: 1 };
    case "list_processing_pending_accounts_processing_pending_get":
      return { items: [], total: 0 };
    case "suggestions_chat_suggestions_get":
      return { suggestions: [], structured_suggestions: [] };
    case "get_available_currencies_reports_currencies_get":
      return ["SGD", "USD"];
    case "get_base_currency_app_config_base_currency_get":
      return { base_currency: "USD" };
    case "get_workflow_status_endpoint_workflow_status_get":
      return {
        primary_state: "ready",
        next_action: { type: "open_report", count: 0, href: "/reports", label: "Open reports", summary: "Reports are ready." },
        report_readiness: { state: "ready", blocking_count: 0, href: "/reports" },
        event_counts: { unread: 0, action_required: 0, blocked: 0 },
      };
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

const netWorth = () => screen.getByText("Net worth").nextElementSibling;

async function settleHome() {
  await waitFor(() => expect(netWorth()).toHaveTextContent("$4,000"));
  await waitFor(() => expect(screen.getByText("Net change").nextElementSibling).toHaveTextContent("+$2,300"));
  await waitFor(() =>
    expect(callKeys().map(operationIdOf)).toContain("list_processing_pending_accounts_processing_pending_get"),
  );
  // The stats report unmatched rows: the banner reads the newest one to name the item (#2646).
  await waitFor(() => expect(callKeys().map(operationIdOf)).toContain("list_unmatched_reconciliation_unmatched_get"));
}

describe("Home fetch budget (#2583 S4)", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      Promise.resolve(respond(operationId, request))) as never);
    setTestUrl("/");
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 cold mount issues each request at most once and reads only the cockpit sources", async () => {
    renderHome(createClient());
    await settleHome();

    const counts = countByKey(callKeys());
    const repeated = [...counts].filter(([, count]) => count > 1);
    expect(repeated, `requests issued more than once: ${JSON.stringify(repeated)}`).toEqual([]);
    expect([...counts.keys()].map(operationIdOf).sort()).toEqual(
      [
        "balance_sheet_reports_balance_sheet_get",
        "balance_sheet_reports_balance_sheet_get",
        "cash_flow_reports_cash_flow_get",
        "get_available_currencies_reports_currencies_get",
        "get_base_currency_app_config_base_currency_get",
        "get_workflow_status_endpoint_workflow_status_get",
        "income_statement_reports_income_statement_get",
        "list_processing_pending_accounts_processing_pending_get",
        "list_statements_statements_get",
        "list_unmatched_reconciliation_unmatched_get",
        "reconciliation_stats_reconciliation_stats_get",
        "report_coverage_reports_coverage_get",
        "suggestions_chat_suggestions_get",
      ].sort(),
    );
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 a second visit inside the stale time issues no request for cached data", async () => {
    const client = createClient();
    const first = renderHome(client);
    await settleHome();
    first.unmount();
    mockedApiOperation.mockClear();

    renderHome(client);
    await waitFor(() => expect(netWorth()).toHaveTextContent("$4,000"));

    const secondVisit = callKeys().filter((key) => operationIdOf(key) !== "get_workflow_status_endpoint_workflow_status_get");
    expect(secondVisit).toEqual([]);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 toggling restricted holdings refetches only the two balance sheets", async () => {
    renderHome(createClient());
    await settleHome();
    mockedApiOperation.mockClear();

    fireEvent.click(screen.getByLabelText("Include restricted holdings"));
    await waitFor(() => expect(screen.getByText("Liquid net worth").nextElementSibling).toHaveTextContent("$1,500"));

    const keys = callKeys();
    expect(keys.map(operationIdOf)).toEqual(["balance_sheet_reports_balance_sheet_get", "balance_sheet_reports_balance_sheet_get"]);
    for (const key of keys) expect(key).toContain('"include_restricted":false');
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 changing the period refetches only the statement requests whose dates changed", async () => {
    renderHome(createClient());
    await settleHome();
    mockedApiOperation.mockClear();

    // 1Y and 1M both end today: the balance sheet at the period end comes from the cache.
    fireEvent.click(screen.getByRole("button", { name: "Period 1M" }));
    await waitFor(() => expect(callKeys()).toHaveLength(3));
    await waitFor(() => expect(screen.getByRole("button", { name: "Period 1M" })).toHaveAttribute("aria-pressed", "true"));

    expect(callKeys().map(operationIdOf).sort()).toEqual([...STATEMENT_OPERATIONS].sort());
    const openingDate = callKeys().find((key) => key.startsWith("balance_sheet"))!;
    expect(openingDate).toMatch(/"as_of_date":"\d{4}-\d{2}-\d{2}"/);
  });

  // AC-reporting.fe-fetch-budget.1
  it("AC-reporting.fe-fetch-budget.1 renders each card from its own data while a slower request is still pending", async () => {
    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: Record<string, unknown> }) =>
      operationId === "cash_flow_reports_cash_flow_get"
        ? new Promise(() => {})
        : Promise.resolve(respond(operationId, request))) as never);

    renderHome(createClient());

    await waitFor(() => expect(netWorth()).toHaveTextContent("$4,000"));
    // The income statement waits for the coverage start, then renders before the cash flow (#2646).
    await waitFor(() => expect(screen.getByText("Net income").nextElementSibling).toHaveTextContent("+$2,300"));
    expect(screen.getByTestId("cockpit-card-cash-flow")).toHaveTextContent("Loading…");
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
    await settleHome();

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
