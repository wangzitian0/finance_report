import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AccountLineageDrawer } from "@/components/reports/AccountLineageDrawer"
import { apiOperation } from "@/lib/api-client"

vi.mock("@/components/ui/Overlay", () => ({
  Sheet: ({
    isOpen,
    title,
    children,
    onClose,
  }: {
    isOpen: boolean
    title: string
    children: ReactNode
    onClose: () => void
  }) =>
    isOpen ? (
      <div role="dialog" aria-label={title}>
        <button onClick={onClose}>{`Close ${title}`}</button>
        {children}
      </div>
    ) : null,
}))

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }))

const mockedApiOperation = vi.mocked(apiOperation)

const TARGET = {
  accountId: "22222222-2222-4222-8222-222222222222",
  accountName: "Checking",
  asOfDate: "2026-01-31",
  currency: "SGD",
}

beforeEach(() => {
  mockedApiOperation.mockReset()
})

describe("Account drill-down to source transactions (EPIC-022 AC22.3.4/AC22.3.5)", () => {
  // AC-reporting.fe-ia-reports.4
  it("AC22.3.4 lists contributing journal lines and opens the lineage chain for one", async () => {
    mockedApiOperation.mockImplementation((operationId: string) => {
      if (operationId === "account_lineage_reports_account_lineage_get") {
        return Promise.resolve({
          account_id: TARGET.accountId,
          account_name: "Checking",
          account_type: "ASSET",
          currency: "SGD",
          as_of_date: "2026-01-31",
          start_date: null,
          total: "750.00",
          lines: [
            {
              journal_line_id: "33333333-3333-4333-8333-333333333333",
              journal_entry_id: "44444444-4444-4444-8444-444444444444",
              entry_date: "2026-01-10",
              memo: "Salary deposit",
              direction: "DEBIT",
              original_amount: "1000.00",
              original_currency: "SGD",
              amount: "1000.00",
            },
            {
              // Empty memo exercises the "Journal line" fallback label.
              journal_line_id: "55555555-5555-4555-8555-555555555555",
              journal_entry_id: "44444444-4444-4444-8444-444444444444",
              entry_date: "2026-01-12",
              memo: "",
              direction: "CREDIT",
              original_amount: "250.00",
              original_currency: "SGD",
              amount: "-250.00",
            },
          ],
        })
      }
      if (operationId === "get_evidence_lineage_evidence_lineage_get") {
        return Promise.resolve({
          anchor: null,
          max_depth: 6,
          blockers: [],
          edges: [],
          nodes: [
            { id: "n1", node_kind: "ledger_line", entity_type: "journal_line", entity_id: "j1", properties: {} },
            { id: "n4", node_kind: "source_document", entity_type: "uploaded_document", entity_id: "d1", properties: {} },
          ],
        })
      }
      return Promise.resolve({})
    })

    render(<AccountLineageDrawer target={TARGET} onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText("Salary deposit")).toBeInTheDocument())
    // The memo-less line falls back to a generic label.
    expect(screen.getByText("Journal line")).toBeInTheDocument()
    // Drill from the contributing line into its evidence lineage.
    fireEvent.click(screen.getByText("Salary deposit"))
    await waitFor(() => expect(screen.getByText("source document")).toBeInTheDocument())
    expect(mockedApiOperation).toHaveBeenCalledWith(
      "get_evidence_lineage_evidence_lineage_get",
      expect.objectContaining({
        query: expect.objectContaining({ entity_type: "journal_line" }),
      }),
    )

    // Closing the lineage drawer clears the anchor.
    fireEvent.click(screen.getByText("Close Source lineage"))
    await waitFor(() => expect(screen.queryByText("source document")).toBeNull())
  })

  // AC-reporting.fe-ia-reports.5
  it("AC22.3.5 shows an empty state when no transactions contribute", async () => {
    mockedApiOperation.mockResolvedValue({
      account_id: TARGET.accountId,
      account_name: "Checking",
      account_type: "ASSET",
      currency: "SGD",
      as_of_date: "2026-01-31",
      start_date: null,
      total: "0.00",
      lines: [],
    })

    render(<AccountLineageDrawer target={TARGET} onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText("No source transactions contribute to this balance yet.")).toBeInTheDocument(),
    )
  })

  it("AC22.3.5 surfaces a load error for contributing transactions", async () => {
    mockedApiOperation.mockRejectedValue(new Error("lineage list boom"))

    render(<AccountLineageDrawer target={TARGET} onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText("lineage list boom")).toBeInTheDocument())
  })

  it("AC22.3.5 issues no request and stays closed without a target", () => {
    render(<AccountLineageDrawer target={null} onClose={() => {}} />)

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(mockedApiOperation).not.toHaveBeenCalled()
  })
})
