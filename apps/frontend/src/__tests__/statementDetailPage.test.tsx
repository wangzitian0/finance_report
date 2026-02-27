import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import StatementDetailPage from "@/app/(main)/statements/[id]/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "s1" }),
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, confirmLabel }: { isOpen: boolean; onConfirm: (reason?: string) => void; onCancel: () => void; confirmLabel?: string }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("mock reason")}>Confirm {confirmLabel || "Confirm"}</button>
        <button onClick={onCancel}>Cancel</button>
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
})
