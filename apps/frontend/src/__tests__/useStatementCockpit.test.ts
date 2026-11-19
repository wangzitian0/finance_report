import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readReportFilters } from "@/hooks/useReportFilters";
import { useStatementCockpit } from "@/hooks/useStatementCockpit";
import { apiOperation } from "@/lib/api";
import { CK, CK_EXTRA, eq, mockCockpitApi, OP, wFor } from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), E = expect;
const YTD = readReportFilters(new URLSearchParams(CK.qs), new Date(2026, 9, 22));
const runH = (ov?: Record<string, () => Promise<unknown>>) => { mockCockpitApi(api, ov); return renderHook(() => useStatementCockpit(YTD)).result; };

describe("useStatementCockpit", () => {
  beforeEach(() => { api.mockReset(); });

  it("AC5.35.1 reads 4 sources", async () => {
    const r = runH(); await wFor(() => E(r.current.cashFlow && r.current.openingBalanceSheet).toBeTruthy());
    eq(CK_EXTRA.calls(api), E.arrayContaining(CK.queries));
    eq([api.mock.calls.length, r.current.pending, r.current.error], [4, CK.pending, null]);
  });

  it("AC5.35.2 normalizes fields", async () => {
    const r = runH({ [OP.IS]: () => Promise.resolve({}), [OP.CF]: () => Promise.resolve(CK_EXTRA.cfOv) });
    await wFor(() => E(r.current.balanceSheet && r.current.incomeStatement && r.current.cashFlow).toBeTruthy());
    eq([r.current.balanceSheet?.opening_balance_warnings, r.current.balanceSheet?.fx_warnings], [CK.warn, []]);
    eq([r.current.incomeStatement, r.current.cashFlow], CK_EXTRA.normExpect);
  });

  it("AC5.35.3 retries failed source", async () => {
    let n = 0; const r = runH({ [OP.CF]: () => (++n === 1 ? Promise.reject(new Error("cash flow down")) : Promise.resolve(CK.cfEmpty)) });
    await wFor(() => E(r.current.error).toBe("cash flow down"));
    const b = api.mock.calls.length; act(() => r.current.retry());
    await wFor(() => E(r.current.error).toBeNull()); eq(api.mock.calls.slice(b).map(([op]) => op), [OP.CF]);
  });
});
