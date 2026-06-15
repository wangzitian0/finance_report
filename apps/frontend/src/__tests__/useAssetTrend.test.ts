import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAssetTrend } from "@/hooks/dashboard/useAssetTrend";
import { apiFetch } from "@/lib/api";
import type { BalanceSheetResponse } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

function balanceWith(assets: BalanceSheetResponse["assets"]): BalanceSheetResponse {
  return {
    as_of_date: "2026-02-01",
    currency: "USD",
    assets,
    liabilities: [],
    equity: [],
    total_assets: "0",
    total_liabilities: "0",
    total_equity: "0",
    equation_delta: "0",
    is_balanced: true,
  };
}

describe("useAssetTrend (EPIC-022 AC22.16.3)", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("AC22.16.3 is usable on its own and fetches the trend for the top asset", async () => {
    mockedApiFetch.mockResolvedValue({ points: [{ period_start: "2026-01-01", amount: "5000" }] });
    const balance = balanceWith([
      { account_id: "a1", name: "Cash", type: "asset", amount: "5000" },
      { account_id: "a2", name: "Brokerage", type: "asset", amount: "9000" },
    ]);

    const { result } = renderHook(() => useAssetTrend(balance));

    await waitFor(() => expect(result.current.trend).not.toBeNull());
    // Top asset by amount is the brokerage account.
    expect(result.current.trendAccountName).toBe("Brokerage");
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/reports/trend?account_id=a2&period=monthly",
    );
  });

  it("AC22.16.3 refetches the trend when the selected account changes", async () => {
    mockedApiFetch.mockResolvedValue({ points: [] });
    const balance = balanceWith([
      { account_id: "a1", name: "Cash", type: "asset", amount: "5000" },
      { account_id: "a2", name: "Brokerage", type: "asset", amount: "9000" },
    ]);

    const { result } = renderHook(() => useAssetTrend(balance));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());

    act(() => result.current.setTrendAccountId("a1"));

    await waitFor(() => expect(result.current.trendAccountName).toBe("Cash"));
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/reports/trend?account_id=a1&period=monthly",
    );
  });

  it("AC22.16.3 stays idle with no assets and clears the trend on fetch failure", async () => {
    // Null balance sheet → no fetch, defaults preserved.
    const empty = renderHook(() => useAssetTrend(null));
    expect(empty.result.current.trend).toBeNull();
    expect(empty.result.current.trendAccountName).toBe("Top Asset");
    expect(mockedApiFetch).not.toHaveBeenCalled();

    // A failing trend endpoint degrades to a null trend without throwing.
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockedApiFetch.mockRejectedValue(new Error("trend down"));
    const { result } = renderHook(() =>
      useAssetTrend(balanceWith([{ account_id: "a1", name: "Cash", type: "asset", amount: "5000" }])),
    );

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
    expect(result.current.trend).toBeNull();
  });

  it("AC22.16.3 clears a stale selection when the chosen account leaves the balance sheet", async () => {
    mockedApiFetch.mockResolvedValue({ points: [] });
    const initial = balanceWith([
      { account_id: "a1", name: "Cash", type: "asset", amount: "5000" },
      { account_id: "a2", name: "Brokerage", type: "asset", amount: "9000" },
    ]);
    const { result, rerender } = renderHook(({ bs }) => useAssetTrend(bs), {
      initialProps: { bs: initial },
    });

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
    act(() => result.current.setTrendAccountId("a2"));
    await waitFor(() => expect(result.current.trendAccountId).toBe("a2"));

    // Refreshed balance sheet no longer contains a2 (e.g. restricted toggled
    // off): the stale selection is dropped so the <select> can't show a missing
    // value, and the trend falls back to the top remaining asset.
    const refreshed = balanceWith([{ account_id: "a1", name: "Cash", type: "asset", amount: "5000" }]);
    rerender({ bs: refreshed });

    await waitFor(() => expect(result.current.trendAccountId).toBeNull());
    expect(result.current.trendAccountName).toBe("Cash");
  });
});
