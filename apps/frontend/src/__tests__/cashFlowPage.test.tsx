import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CashFlowPage from "@/app/(main)/reports/cash-flow/page"
import { apiOperation, apiOperationDownload } from "@/lib/api-client"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}))

vi.mock("@/components/charts/SankeyChart", () => ({
  SankeyChart: () => <div>SankeyChartMock</div>,
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD", "EUR"], loading: false }),
}))

vi.mock("@/lib/api-client", () => ({
  API_URL: "http://localhost:8000",
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}))

describe("CashFlowPage", () => {
  const mockedApiDownload = vi.mocked(apiOperationDownload)
  const mockedApiFetch = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiDownload.mockReset()
    mockedApiFetch.mockReset()
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:cash-flow-export"),
      revokeObjectURL: vi.fn(),
    }))
  })

  // AC-reporting.fe-report-surfaces.16
  it("AC16.14.7 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("cashflow failed"))

    const { container } = render(<CashFlowPage />)

    expect(screen.getByRole("status", { name: "Loading cash flow" })).toHaveAttribute("aria-busy", "true")
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(10)
    expect(container.querySelector(".animate-spin")).toBeNull()

    await waitFor(() => expect(screen.getByText("cashflow failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2))
  })

  // AC-reporting.fe-report-surfaces.17
  it("AC16.14.8 / test_AC8_13_48 renders string summary and activity sections", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [{ line_id: "operating-sales", category: "operating", subcategory: "Sales", amount: "1000", description: "Main ops", event_count: 1 }],
      investing: [{ line_id: "investing-etf", category: "investing", subcategory: "ETF", amount: "-300", description: null, event_count: 1 }],
      financing: [{ line_id: "financing-loan", category: "financing", subcategory: "Loan", amount: "200", description: null, event_count: 1 }],
      summary: {
        operating_activities: "1000",
        investing_activities: "-300",
        financing_activities: "200",
        net_cash_flow: "900",
        beginning_cash: "5000",
        ending_cash: "5900",
      },
      fx_warnings: [{ type: "spot_rate_fallback", from_currency: "EUR", to_currency: "SGD", fallback_date: "2026-01-30" }],
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Net Cash Flow")).toBeInTheDocument()
    expect(screen.getByText("Operating Activities")).toBeInTheDocument()
    expect(screen.getByText("Investing Activities")).toBeInTheDocument()
    expect(screen.getByText("Financing Activities")).toBeInTheDocument()
    expect(screen.getByText("Partial FX data used")).toBeInTheDocument()
    expect(screen.getByText("Sales")).toBeInTheDocument()
    expect(screen.getByText("Main ops")).toBeInTheDocument()

    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt=")
    )
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument()

    const netCashFlowCard = screen.getByText("Net Cash Flow").closest("div")
    const beginningCashCard = screen.getByText("Beginning Cash").closest("div")
    const endingCashCard = screen.getByText("Ending Cash").closest("div")
    expect(netCashFlowCard).toHaveTextContent("900.00")
    expect(beginningCashCard).toHaveTextContent("5,000.00")
    expect(endingCashCard).toHaveTextContent("5,900.00")

    // AC22.7.3: beginning + net = ending ties, so it shows a reconciled state.
    const reconciliation = screen.getByLabelText("Cash reconciliation")
    expect(reconciliation).toHaveTextContent("✓ Reconciles")
  })

  // AC-reporting.fe-ia-reports.12
  it("AC22.7.3 flags cash that does not tie (beginning + net != ending)", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0",
        investing_activities: "0",
        financing_activities: "0",
        net_cash_flow: "900",
        beginning_cash: "5000",
        ending_cash: "6500", // expected 5900, so it drifts by 600
      },
    })

    render(<CashFlowPage />)

    const reconciliation = await screen.findByLabelText("Cash reconciliation")
    expect(reconciliation).toHaveTextContent("⚠ Does not tie")
    expect(screen.getByText(/differs from the reported ending/i)).toBeInTheDocument()
    // The drift is shown as a positive amount with an explicit direction, never
    // a confusing negative (reported 6500 > expected 5900).
    expect(reconciliation).toHaveTextContent("the reported ending is higher than expected")
    expect(reconciliation).not.toHaveTextContent("-")
  })

  // AC-reporting.report-integrity.3
  it("discloses midperiod starting stock without claiming complete coverage", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01", end_date: "2026-01-31", currency: "SGD",
      operating: [], investing: [], financing: [],
      summary: {
        operating_activities: "20", investing_activities: "0", financing_activities: "0",
        net_cash_flow: "20", beginning_cash: "0", ending_cash: "120",
      },
      cash_bridge: { opening_stock_adjustment: "100", reconciles: true },
      proof_state: "unproven", proof_reasons: ["opening_coverage_starts_after_period"],
    })
    render(<CashFlowPage />)
    const reconciliation = await screen.findByLabelText("Cash reconciliation")
    expect(screen.getByText("Known Beginning Cash")).toBeInTheDocument()
    expect(reconciliation).toHaveTextContent("Opening balance adjustment")
    expect(reconciliation).toHaveTextContent("100.00")
    expect(reconciliation).toHaveTextContent("Coverage incomplete")
    expect(reconciliation).not.toHaveTextContent("✓ Reconciles")
    expect(reconciliation).not.toHaveTextContent("Does not tie")
    expect(screen.getByText(/records start after the selected period begins/i)).toBeInTheDocument()
  })

  // AC-reporting.report-integrity.3
  it("does not call an arithmetically tied report verified after opening authority is lost", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01", end_date: "2026-01-31", currency: "SGD",
      operating: [], investing: [], financing: [],
      summary: {
        operating_activities: "20", investing_activities: "0", financing_activities: "0",
        net_cash_flow: "20", beginning_cash: "100", ending_cash: "120",
      },
      cash_bridge: { reconciles: true },
      proof_state: "unproven", proof_reasons: ["opening_position_unproven"],
    })
    render(<CashFlowPage />)
    const reconciliation = await screen.findByLabelText("Cash reconciliation")
    expect(reconciliation).toHaveTextContent("Not yet verified")
    expect(reconciliation).not.toHaveTextContent("✓ Reconciles")
    expect(screen.getByText(/opening balance evidence needs review/i)).toBeInTheDocument()
  })

  // AC-reporting.fe-ia-reports.10
  it("AC22.7.1 drills a cash-flow amount down to its account lineage", async () => {
    mockedApiFetch.mockImplementation((operationId: string) => {
      if (operationId === "cash_flow_reports_cash_flow_get") {
        return Promise.resolve({
          start_date: "2026-01-01",
          end_date: "2026-02-01",
          currency: "SGD",
          operating: [
            { line_id: "operating-salary", category: "operating", subcategory: "Salary", amount: "500", description: "Inflow - Salary", account_id: "acc-salary", event_count: 1 },
          ],
          investing: [],
          financing: [],
          summary: {
            operating_activities: "500", investing_activities: "0", financing_activities: "0",
            net_cash_flow: "500", beginning_cash: "1000", ending_cash: "1500",
          },
        })
      }
      if (operationId === "account_lineage_reports_account_lineage_get") {
        return Promise.resolve({
          account_id: "acc-salary", account_name: "Salary", account_type: "INCOME",
          currency: "SGD", as_of_date: "2026-02-01", start_date: "2026-01-01",
          total: "500.00", lines: [],
        })
      }
      return Promise.resolve({})
    })

    render(<CashFlowPage />)

    const amount = await screen.findByRole("button", { name: /View source transactions for Salary/i })
    fireEvent.click(amount)

    const dialog = await screen.findByRole("dialog")
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "account_lineage_reports_account_lineage_get",
        expect.objectContaining({
          query: expect.objectContaining({ account_id: "acc-salary" }),
        }),
      ),
    )

    // Closing the drawer clears the drill target.
    fireEvent.click(within(dialog).getByRole("button", { name: /close/i }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  // AC-reporting.fe-fetch-budget.8
  it("AC-reporting.fe-fetch-budget.8 loads the events of a cash-flow line only after the user expands the line", async () => {
    const lineEventsOperation = "list_cash_flow_line_events_reports_cash_flow_line_events_get"
    const lineEvent = (id: string, memo: string, amount: string, entryDate: string) => ({
      journal_entry_id: id,
      journal_line_ids: [`${id}-cash`, `${id}-counter`],
      source_type: "system",
      source_id: null,
      decision_anchor_id: null,
      decision_authority_state: "anchored",
      event_types: [],
      activity: "Operating",
      reason_code: null,
      entry_date: entryDate,
      memo,
      amount,
    })
    mockedApiFetch.mockImplementation((operationId: string, request?: unknown) => {
      if (operationId === "cash_flow_reports_cash_flow_get") {
        return Promise.resolve({
          start_date: "2026-01-01",
          end_date: "2026-01-31",
          currency: "SGD",
          operating: [
            { line_id: "operating-salary", category: "Operating", subcategory: "Salary", amount: "9000.00", description: "Inflow - Salary", account_id: "acc-salary", event_count: 3 },
            { line_id: "operating-groceries", category: "Operating", subcategory: "Groceries", amount: "-105.00", description: "Outflow - Groceries", account_id: "acc-groceries", event_count: 201 },
          ],
          investing: [],
          financing: [],
          summary: {
            operating_activities: "8895.00", investing_activities: "0.00", financing_activities: "0.00",
            net_cash_flow: "8895.00", beginning_cash: "0.00", ending_cash: "8895.00",
          },
          lineage_summary: { event_count: 204, classified_event_count: 204, unclassified_event_count: 0, opening_stock_event_count: 0 },
          proof_state: "proven",
          proof_reasons: [],
        })
      }
      if (operationId === lineEventsOperation) {
        const { offset } = (request as { query: { offset: number } }).query
        return Promise.resolve({
          line_id: "operating-groceries",
          total: 201,
          limit: 200,
          offset,
          events:
            offset === 0
              ? [lineEvent("entry-1", "Groceries Jan 3", "-40.00", "2026-01-03"), lineEvent("entry-2", "Groceries Jan 9", "-25.00", "2026-01-09")]
              : [lineEvent("entry-3", "Groceries Jan 12", "-40.00", "2026-01-12")],
        })
      }
      return Promise.resolve({})
    })
    const lineEventCalls = () => mockedApiFetch.mock.calls.filter(([operationId]) => operationId === lineEventsOperation)

    render(<CashFlowPage />)

    const toggle = await screen.findByRole("button", { name: "201 events for Outflow - Groceries" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(toggle).toHaveTextContent("201 events")
    expect(screen.getByRole("button", { name: "3 events for Inflow - Salary" })).toHaveTextContent("3 events")
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(lineEventCalls()).toHaveLength(0)
    expect(screen.queryByText("Groceries Jan 3")).not.toBeInTheDocument()

    fireEvent.click(toggle)

    const events = await screen.findByRole("region", { name: "Events for Outflow - Groceries" })
    await waitFor(() => expect(within(events).getByText("Groceries Jan 3")).toBeInTheDocument())
    expect(within(events).getByText("Groceries Jan 9")).toBeInTheDocument()
    expect(within(events).getByText("2 of 201 events")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "201 events for Outflow - Groceries" })).toHaveAttribute("aria-expanded", "true")
    expect(lineEventCalls()).toHaveLength(1)
    expect(lineEventCalls()[0][1]).toMatchObject({
      query: { start_date: "2026-01-01", end_date: "2026-01-31", currency: "SGD", line_id: "operating-groceries", limit: 200, offset: 0 },
    })

    fireEvent.click(within(events).getByRole("button", { name: "Load more events" }))
    await waitFor(() => expect(within(events).getByText("Groceries Jan 12")).toBeInTheDocument())
    expect(within(events).getByText("3 of 201 events")).toBeInTheDocument()
    expect(lineEventCalls()).toHaveLength(2)
    expect(lineEventCalls()[1][1]).toMatchObject({ query: { line_id: "operating-groceries", offset: 200 } })

    // Closing and opening the line again reads the cached pages without a request.
    fireEvent.click(screen.getByRole("button", { name: "201 events for Outflow - Groceries" }))
    expect(screen.queryByRole("region", { name: "Events for Outflow - Groceries" })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "201 events for Outflow - Groceries" }))
    expect(await screen.findByText("Groceries Jan 12")).toBeInTheDocument()
    expect(lineEventCalls()).toHaveLength(2)
    expect(lineEventCalls().every(([, request]) => (request as { query: { line_id: string } }).query.line_id === "operating-groceries")).toBe(true)
  })

  it("keeps the loaded events of a line visible when a later page fails", async () => {
    mockedApiFetch.mockImplementation((operationId: string, request?: unknown) => {
      if (operationId === "cash_flow_reports_cash_flow_get") {
        return Promise.resolve({
          start_date: "2026-01-01",
          end_date: "2026-01-31",
          currency: "SGD",
          operating: [
            { line_id: "operating-groceries", category: "Operating", subcategory: "Groceries", amount: "-40.00", description: "Outflow - Groceries", account_id: "acc-groceries", event_count: 201 },
          ],
          investing: [],
          financing: [],
          summary: {
            operating_activities: "-40.00", investing_activities: "0.00", financing_activities: "0.00",
            net_cash_flow: "-40.00", beginning_cash: "100.00", ending_cash: "60.00",
          },
          lineage_summary: { event_count: 201, classified_event_count: 201, unclassified_event_count: 0, opening_stock_event_count: 0 },
          proof_state: "proven",
          proof_reasons: [],
        })
      }
      if ((request as { query: { offset: number } }).query.offset > 0) {
        return Promise.reject(new Error("events page failed"))
      }
      return Promise.resolve({
        line_id: "operating-groceries",
        total: 201,
        limit: 200,
        offset: 0,
        events: [
          {
            journal_entry_id: "entry-1", journal_line_ids: ["l1", "l2"], source_type: "system", source_id: null,
            decision_anchor_id: null, decision_authority_state: "anchored", event_types: [], activity: "Operating",
            reason_code: null, entry_date: "2026-01-03", memo: "Groceries Jan 3", amount: "-40.00",
          },
        ],
      })
    })

    render(<CashFlowPage />)
    fireEvent.click(await screen.findByRole("button", { name: "201 events for Outflow - Groceries" }))
    const events = await screen.findByRole("region", { name: "Events for Outflow - Groceries" })
    await waitFor(() => expect(within(events).getByText("Groceries Jan 3")).toBeInTheDocument())

    fireEvent.click(within(events).getByRole("button", { name: "Load more events" }))

    await waitFor(() => expect(within(events).getByText("events page failed")).toBeInTheDocument())
    expect(within(events).getByText("Groceries Jan 3")).toBeInTheDocument()
  })

  // AC-reporting.fe-report-surfaces.18
  it("AC16.14.9 renders sankey chart when summary exists", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: 0,
        investing_activities: 0,
        financing_activities: 0,
        net_cash_flow: 0,
        beginning_cash: 0,
        ending_cash: 0,
      },
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("SankeyChartMock")).toBeInTheDocument())
  })

  it("AC5.17.1 downloads cash-flow CSV through authenticated apiDownload", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0",
        investing_activities: "0",
        financing_activities: "0",
        net_cash_flow: "0",
        beginning_cash: "0",
        ending_cash: "0",
      },
    })
    mockedApiDownload.mockResolvedValue({
      blob: new Blob(["section,account,amount\n"], { type: "text/csv" }),
      filename: "cash-flow-2026-01-01-to-2026-01-31.csv",
    })

    render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-01-01" } })
    await waitFor(() => expect(screen.getByLabelText("End date")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-01-31" } })
    await waitFor(() => expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }))

    await waitFor(() =>
      expect(mockedApiDownload).toHaveBeenCalledWith(
        "export_report_reports_export_get",
        expect.objectContaining({
          query: expect.objectContaining({
            report_type: "cash-flow",
            start_date: "2026-01-01",
            end_date: "2026-01-31",
            currency: "SGD",
          }),
        }),
      ),
    )
  })

  it("AC16.14.10 / test_AC8_13_48 refetches when filters and dates change", async () => {
    mockedApiFetch.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      currency: "USD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: 0,
        investing_activities: 0,
        financing_activities: 0,
        net_cash_flow: 0,
        beginning_cash: 0,
        ending_cash: 0,
      },
    })

    const { container } = render(<CashFlowPage />)

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "USD" } })

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(
        "cash_flow_reports_cash_flow_get",
        expect.objectContaining({
          query: expect.objectContaining({ currency: "USD" }),
        }),
      ),
    )
    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())

    const dateInputs = container.querySelectorAll('input[type="date"]')
    expect(dateInputs).toHaveLength(2)
    fireEvent.change(dateInputs[0], { target: { value: "2026-01-15" } })
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(
        "cash_flow_reports_cash_flow_get",
        expect.objectContaining({
          query: expect.objectContaining({ start_date: "2026-01-15" }),
        }),
      ),
    )
    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    fireEvent.change(container.querySelectorAll('input[type="date"]')[1], { target: { value: "2026-02-15" } })
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(
        "cash_flow_reports_cash_flow_get",
        expect.objectContaining({
          query: expect.objectContaining({ end_date: "2026-02-15" }),
        }),
      ),
    )
    const lastCall = mockedApiFetch.mock.calls.at(-1)
    expect(lastCall?.[0]).toBe("cash_flow_reports_cash_flow_get")
    expect((lastCall?.[1] as any)?.query).toMatchObject({
      start_date: "2026-01-15",
      end_date: "2026-02-15",
    })
    expect(screen.getAllByText("No items in this category.")).toHaveLength(3)

    fireEvent.click(screen.getByRole("button", { name: "Period 1Q" }))
    expect(screen.getByRole("button", { name: "Period 1Q" })).toHaveAttribute("aria-pressed", "true")
  })
})
