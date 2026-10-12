import { renderHook, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardData } from "@/hooks/useDashboardData";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

const mockedApiOperation = vi.mocked(apiOperation);

function mapDashboardOperationToLegacy(operationId: string, req: any = {}): [string, RequestInit | undefined] {
  switch (operationId) {
    case "balance_sheet_reports_balance_sheet_get":
      return ["/api/reports/balance-sheet", undefined];
    case "income_statement_reports_income_statement_get":
      return ["/api/reports/income-statement", undefined];
    case "get_annualized_income_income_annualized_get":
      return ["/api/income/annualized", undefined];
    case "list_restricted_holdings_assets_restricted_get":
      return ["/api/assets/restricted", undefined];
    case "reconciliation_stats_reconciliation_stats_get":
      return ["/api/reconciliation/stats", undefined];
    case "list_unmatched_reconciliation_unmatched_get":
      return ["/api/reconciliation/unmatched", undefined];
    case "list_journal_entries_journal_entries_get":
      return ["/api/journal-entries", undefined];
    case "list_accounts_accounts_get":
      return ["/api/accounts", undefined];
    case "list_statements_statements_get":
      return ["/api/statements", undefined];
    case "suggestions_chat_suggestions_get":
      return ["/api/chat/suggestions", undefined];
    case "account_trend_reports_trend_get":
      return ["/api/reports/trend", undefined];
    default:
      return [operationId, req];
  }
}

function routeResponder(map: Record<string, unknown>, fallback?: (path: string) => unknown) {
  return (path: string) => {
    const key = Object.keys(map).find((prefix) => path.startsWith(prefix));
    if (key) return Promise.resolve(map[key]);
    if (fallback) return Promise.resolve(fallback(path));
    return Promise.resolve(undefined);
  };
}

describe("useDashboardData", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
    const originalMockImplementation = mockedApiOperation.mockImplementation.bind(mockedApiOperation);
    mockedApiOperation.mockImplementation = (fn: any) => {
      return originalMockImplementation((operationId: any, req: any) => {
        if (typeof operationId === "string" && operationId.startsWith("/")) {
          return fn(operationId, req);
        }
        const [path, options] = mapDashboardOperationToLegacy(operationId, req);
        return fn(path, options);
      });
    };
  });

  // AC-reporting.fe-viz-reports.24
  it("AC5.35.1 aggregates dashboard endpoints over apiFetch", async () => {
    mockedApiOperation.mockImplementation((path: string) =>
      routeResponder({
        "/api/reports/balance-sheet": {
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
        },
        "/api/reports/income-statement": {
          currency: "USD",
          trends: [],
          income: [],
          expenses: [],
          total_income: "3500",
          total_expenses: "1200",
          net_income: "2300",
        },
        "/api/income/annualized": {
          annualized_total: "42000",
          currency: "USD",
        },
        "/api/chat/suggestions": { suggestions: [], structured_suggestions: [] },
      })(path),
    );

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.balanceSheet?.total_assets).toBe("5000");
    expect(result.current.incomeStatement?.total_income).toBe("3500");
    expect(result.current.annualizedIncome?.annualized_total).toBe("42000");
    expect(mockedApiOperation).toHaveBeenCalledWith(
      "balance_sheet_reports_balance_sheet_get",
      expect.anything(),
    );
  });

  // AC-reporting.fe-viz-reports.25
  it("AC5.35.2 normalizes missing report fields to defaults", async () => {
    // Backend returns sparse payloads (only a few fields populated).
    mockedApiOperation.mockImplementation((path: string) =>
      routeResponder(
        {
          "/api/reports/balance-sheet": { currency: "SGD" },
          "/api/reports/income-statement": { currency: "SGD" },
          "/api/income/annualized": {},
          "/api/chat/suggestions": { suggestions: [], structured_suggestions: [] },
        },
        () => null,
      )(path),
    );

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.balanceSheet?.total_assets).toBe("0");
    expect(result.current.balanceSheet?.assets).toEqual([]);
    expect(result.current.incomeStatement?.net_income).toBe("0");
    expect(result.current.annualizedIncome?.annualized_total).toBe("0");
    expect(result.current.restrictedHoldings).toEqual([]);
  });

  // AC-reporting.fe-viz-reports.26
  it("AC5.35.3 surfaces error and retries on failure", async () => {
    mockedApiOperation.mockReturnValue(Promise.reject(new Error("network down")));

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("network down");

    // Recover on retry.
    mockedApiOperation.mockImplementation((path: string) =>
      routeResponder(
        {
          "/api/reports/balance-sheet": { currency: "SGD" },
          "/api/reports/income-statement": { currency: "SGD" },
          "/api/income/annualized": {},
          "/api/chat/suggestions": { suggestions: [], structured_suggestions: [] },
        },
        () => null,
      )(path),
    );

    await act(async () => {
      result.current.retry();
    });

    await waitFor(() => expect(result.current.error).toBeNull());
  });

  // AC-reporting.fe-ia-reports.22
  it("AC22.16.3 composes the snapshot and asset-trend hooks, exposing the trend once the balance loads", async () => {
    mockedApiOperation.mockImplementation((path: string) =>
      routeResponder(
        {
          "/api/reports/balance-sheet": {
            assets: [{ account_id: "a1", name: "Cash", type: "ASSET", amount: "5000" }],
            liabilities: [],
            equity: [],
            total_assets: "5000",
            total_liabilities: "0",
            total_equity: "5000",
            equation_delta: "0",
            currency: "USD",
            as_of_date: "2026-02-01",
            is_balanced: true,
          },
          "/api/reports/income-statement": { currency: "USD" },
          "/api/income/annualized": {},
          "/api/reports/trend": { points: [{ period_start: "2026-01-01", amount: "5000" }] },
          "/api/chat/suggestions": { suggestions: [], structured_suggestions: [] },
        },
        () => null,
      )(path),
    );

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    // The aggregate keeps its public contract: snapshot fields plus the trend
    // resolved by the composed useAssetTrend hook for the top asset.
    await waitFor(() => expect(result.current.trend).not.toBeNull());
    expect(result.current.trendAccountName).toBe("Cash");
    expect(mockedApiOperation).toHaveBeenCalledWith(
      "account_trend_reports_trend_get",
      expect.objectContaining({ query: expect.objectContaining({ account_id: "a1", period: "monthly" }) }),
    );
  });

  // AC-reporting.fe-viz-reports.27
  it("AC5.35.4 tolerates failing chat suggestions endpoint", async () => {
    mockedApiOperation.mockImplementation((path: string) => {
      if (path.startsWith("/api/chat/suggestions")) {
        return Promise.reject(new Error("suggestions unavailable"));
      }
      return routeResponder(
        {
          "/api/reports/balance-sheet": { currency: "SGD" },
          "/api/reports/income-statement": { currency: "SGD" },
          "/api/income/annualized": {},
        },
        () => null,
      )(path);
    });

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.advisorSuggestions).toEqual([]);
  });
});
