import { renderHook, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardData } from "@/hooks/useDashboardData";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

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
    mockedApiFetch.mockReset();
  });

  it("AC5.35.1 aggregates dashboard endpoints over apiFetch", async () => {
    mockedApiFetch.mockImplementation((path: string) =>
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
    expect(mockedApiFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/reports/balance-sheet"),
    );
  });

  it("AC5.35.2 normalizes missing report fields to defaults", async () => {
    // Backend returns sparse payloads (only a few fields populated).
    mockedApiFetch.mockImplementation((path: string) =>
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

  it("AC5.35.3 surfaces error and retries on failure", async () => {
    mockedApiFetch.mockReturnValue(Promise.reject(new Error("network down")));

    const { result } = renderHook(() => useDashboardData(false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("network down");

    // Recover on retry.
    mockedApiFetch.mockImplementation((path: string) =>
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

  it("AC5.35.4 tolerates failing chat suggestions endpoint", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
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
