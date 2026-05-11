import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import StatementDetailPage from "@/app/(main)/statements/[id]/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()
const mockSearchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "s1" }),
  useSearchParams: () => mockSearchParams,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, confirmLabel }: { isOpen: boolean; onConfirm: (reason?: string) => void; onCancel: () => void; confirmLabel?: string }) =>
    isOpen ? (
      <div>
        <button type="button" onClick={() => onConfirm("mock reason")}>Confirm {confirmLabel || "Confirm"}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const parsedStatement = {
  id: "s1",
  original_filename: "statement-jan.pdf",
  institution: "DBS",
  currency: "SGD",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  opening_balance: 1000,
  closing_balance: 1500,
  confidence_score: 92,
  balance_validated: true,
  validation_error: null,
  status: "parsed",
  parsing_progress: 100,
  transactions: [
    {
      id: "t1",
      txn_date: "2026-01-02",
      description: "Salary",
      reference: "R1",
      amount: 500,
      direction: "IN",
      currency: "SGD",
      balance_after: 1500,
      confidence: "high",
      status: "matched",
    },
  ],
}

describe("StatementDetailPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    mockSearchParams.delete("approved")
    mockSearchParams.delete("entriesCreated")
  })

  it("AC16.18.1 loads detail data and renders transactions", async () => {
    mockedApiFetch.mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument()
  })

  it("AC16.18.2 approve and reject actions call APIs", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(parsedStatement)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(parsedStatement)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Approve" }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm Approve" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/approve", {
        method: "POST",
        body: JSON.stringify({ notes: null }),
      }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm Reject" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/reject", {
        method: "POST",
        body: JSON.stringify({ notes: "mock reason" }),
      }),
    )
  })

  it("AC16.18.3 retry parse posts retry API and refreshes", async () => {
    const rejectedStatement = { ...parsedStatement, status: "rejected", validation_error: "parse failed" }
    mockedApiFetch.mockResolvedValueOnce(rejectedStatement).mockResolvedValueOnce(undefined).mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("Parsing Failed")).toBeInTheDocument())
    fireEvent.click(screen.getAllByRole("button", { name: "Retry Parse" })[0])

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/retry", {
        method: "POST",
      }),
    )
  })

  it("shows not found state", async () => {
    mockedApiFetch.mockResolvedValueOnce(null)
    render(<StatementDetailPage />)
    await waitFor(() => expect(screen.getByText("Statement not found")).toBeInTheDocument())
  })

  it("handles confirm dialog cancel", async () => {
    mockedApiFetch.mockResolvedValueOnce(parsedStatement)
    render(<StatementDetailPage />)
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Approve" }))
    fireEvent.click(screen.getByText("Cancel"))
    expect(screen.queryByText("Confirm Approve")).not.toBeInTheDocument()
  })

  it("shows post-approval CTA when redirected from approve flow", async () => {
    mockSearchParams.set("approved", "1")
    mockSearchParams.set("entriesCreated", "42")
    mockedApiFetch.mockResolvedValueOnce({ ...parsedStatement, status: "approved" })

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("Statement approved. 42 journal entries created.")).toBeInTheDocument())
    expect(screen.getByRole("link", { name: "View in Journal" })).toHaveAttribute("href", "/journal")
    expect(screen.getByRole("link", { name: "Go to Reports" })).toHaveAttribute("href", "/reports")
  })

  it("does not show post-approval CTA when statement is not approved", async () => {
    mockSearchParams.set("approved", "1")
    mockSearchParams.set("entriesCreated", "42")
    mockedApiFetch.mockResolvedValueOnce({ ...parsedStatement, status: "parsed" })

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("Review")).toBeInTheDocument())
    expect(screen.queryByText("Statement approved. 42 journal entries created.")).not.toBeInTheDocument()
  })

  it("stops polling after consecutive errors", async () => {
    const parsingState = { ...parsedStatement, status: "parsing", parsing_progress: 50 }
    mockedApiFetch.mockResolvedValueOnce(parsingState)
    mockedApiFetch.mockRejectedValue(new Error("Poll Failure"))
    render(<StatementDetailPage />)
    await waitFor(() => expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument(), { timeout: 3000 })
    await waitFor(() => expect(screen.getByText(/Auto-refresh Stopped/)).toBeInTheDocument(), { timeout: 15000 })
  }, 20000)
})
