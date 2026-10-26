import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { readReportFilters } from "@/hooks/useReportFilters"
import { useStatementCockpit } from "@/hooks/useStatementCockpit"
import { apiOperation } from "@/lib/api-client"

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const mockedApiOperation = vi.mocked(apiOperation)
const YTD_JUNE = readReportFilters(new URLSearchParams("period=YTD&end=2026-06-30&currency=USD&include_restricted=true"), new Date(2026, 9, 22))

const balanceSheet = {
  as_of_date: "2026-06-30",
  currency: "USD",
  assets: [],
  liabilities: [],
  equity: [],
  total_assets: "100",
  total_liabilities: "0",
  total_equity: "100",
  equation_delta: "0",
  is_balanced: true,
  opening_balance_warnings: [{ message: "Record opening balances." }],
}

function answer(overrides: Partial<Record<string, () => Promise<unknown>>> = {}) {
  mockedApiOperation.mockImplementation(((operationId: string) => {
    if (overrides[operationId]) return overrides[operationId]!()
    if (operationId === "balance_sheet_reports_balance_sheet_get") return Promise.resolve(balanceSheet)
    if (operationId === "income_statement_reports_income_statement_get") {
      return Promise.resolve({ currency: "USD", income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0", trends: [] })
    }
    if (operationId === "cash_flow_reports_cash_flow_get") {
      return Promise.resolve({ currency: "USD", operating: [], investing: [], financing: [], summary: {} })
    }
    return Promise.reject(new Error(`unexpected ${operationId}`))
  }) as never)
}

describe("useStatementCockpit", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset()
  })

  // AC-reporting.fe-viz-reports.24
  it("AC5.35.1 reads the four statement sources of the dimension-bar period", async () => {
    answer()
    const { result } = renderHook(() => useStatementCockpit(YTD_JUNE))

    await waitFor(() => expect(result.current.cashFlow).not.toBeNull())
    await waitFor(() => expect(result.current.openingBalanceSheet).not.toBeNull())
    expect(mockedApiOperation.mock.calls.map(([operationId, request]) => [operationId, (request as { query: unknown }).query])).toEqual(
      expect.arrayContaining([
        ["balance_sheet_reports_balance_sheet_get", { as_of_date: "2026-06-30", currency: "USD", include_restricted: true }],
        ["balance_sheet_reports_balance_sheet_get", { as_of_date: "2025-12-31", currency: "USD", include_restricted: true }],
        ["income_statement_reports_income_statement_get", { start_date: "2026-01-01", end_date: "2026-06-30", currency: "USD" }],
        ["cash_flow_reports_cash_flow_get", { start_date: "2026-01-01", end_date: "2026-06-30", currency: "USD" }],
      ]),
    )
    expect(mockedApiOperation).toHaveBeenCalledTimes(4)
    expect(result.current.pending).toEqual({ balanceSheet: false, incomeStatement: false, cashFlow: false })
    expect(result.current.error).toBeNull()
  })

  // AC-reporting.fe-viz-reports.25
  it("AC5.35.2 normalizes missing statement fields to empty lists, zero decimal strings and typed warnings", async () => {
    answer({
      income_statement_reports_income_statement_get: () => Promise.resolve({}),
      cash_flow_reports_cash_flow_get: () => Promise.resolve({ currency: "USD", summary: { net_cash_flow: "12.50" } }),
    })
    const { result } = renderHook(() => useStatementCockpit(YTD_JUNE))

    await waitFor(() => expect(result.current.balanceSheet).not.toBeNull())
    expect(result.current.balanceSheet?.opening_balance_warnings).toEqual([{ message: "Record opening balances.", type: "unknown" }])
    expect(result.current.balanceSheet?.fx_warnings).toEqual([])
    await waitFor(() => expect(result.current.incomeStatement).not.toBeNull())
    expect(result.current.incomeStatement).toMatchObject({
      currency: "SGD",
      income: [],
      expenses: [],
      total_income: "0",
      total_expenses: "0",
      net_income: "0",
    })
    await waitFor(() => expect(result.current.cashFlow).not.toBeNull())
    expect(result.current.cashFlow).toMatchObject({
      currency: "USD",
      operating: [],
      investing: [],
      financing: [],
      summary: { operating_activities: "0", investing_activities: "0", financing_activities: "0", net_cash_flow: "12.50" },
    })
  })

  // AC-reporting.fe-viz-reports.26
  it("AC5.35.3 surfaces the first error and a retry that refetches only the failed source", async () => {
    let cashFlowCalls = 0
    answer({
      cash_flow_reports_cash_flow_get: () => {
        cashFlowCalls += 1
        return cashFlowCalls === 1
          ? Promise.reject(new Error("cash flow down"))
          : Promise.resolve({ currency: "USD", operating: [], investing: [], financing: [], summary: {} })
      },
    })
    const { result } = renderHook(() => useStatementCockpit(YTD_JUNE))

    await waitFor(() => expect(result.current.error).toBe("cash flow down"))
    const callsBeforeRetry = mockedApiOperation.mock.calls.length
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.error).toBeNull())
    expect(mockedApiOperation.mock.calls.slice(callsBeforeRetry).map(([operationId]) => operationId)).toEqual(["cash_flow_reports_cash_flow_get"])
  })
})
