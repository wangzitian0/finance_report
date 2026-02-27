import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import StatementReviewPage from "@/app/(main)/statements/[id]/review/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()
const pushMock = vi.fn()

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "s1" }),
  useRouter: () => ({ push: pushMock }),
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, confirmLabel }: { isOpen: boolean; onConfirm: (reason?: string) => void; onCancel: () => void; confirmLabel?: string }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("review reason")}>Confirm {confirmLabel || "Confirm"}</button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const reviewData = {
  id: "s1",
  original_filename: "statement-jan.pdf",
  institution: "DBS",
  currency: "SGD",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  opening_balance: 1000,
  closing_balance: 1500,
  status: "parsed",
  stage1_status: "completed",
  balance_validation_result: {
    opening_balance: "1000.00",
    closing_balance: "1500.00",
    calculated_closing: "1500.00",
    opening_delta: "0.00",
    closing_delta: "0.00",
    opening_match: true,
    closing_match: true,
    validated_at: "2026-01-31T00:00:00Z",
  },
  pdf_url: null,
  transactions: [
    {
      id: "t1",
      txn_date: "2026-01-05",
      description: "Salary",
      amount: 500,
      direction: "IN",
      reference: null,
      currency: "SGD",
      balance_after: 1500,
      status: "matched",
      confidence: "high",
    },
  ],
}

describe("StatementReviewPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    pushMock.mockReset()
  })

  it("AC16.18.4 shows error fallback and supports retry", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("review failed")).mockResolvedValueOnce(reviewData)

    render(<StatementReviewPage />)

    await waitFor(() => expect(screen.getByText("Failed to load statement")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
  })

  it("AC16.18.5 disables approve when balance validation fails", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      ...reviewData,
      balance_validation_result: {
        ...reviewData.balance_validation_result,
        closing_match: false,
        closing_delta: "12.00",
      },
    })

    render(<StatementReviewPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    const approveButton = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement
    expect(approveButton.disabled).toBe(true)
    expect(approveButton.getAttribute("title")).toBe("Balance validation failed - cannot approve")
  })

  it("AC16.18.6 approve and reject call APIs and navigate", async () => {
    mockedApiFetch.mockResolvedValueOnce(reviewData).mockResolvedValueOnce(undefined).mockResolvedValueOnce(undefined)

    render(<StatementReviewPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Approve" }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm Approve" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/review/approve", {
        method: "POST",
      }),
    )
    expect(pushMock).toHaveBeenCalledWith("/statements")

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm Reject" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/review/reject", {
        method: "POST",
        body: JSON.stringify({ notes: "review reason" }),
      }),
    )
  })
})
