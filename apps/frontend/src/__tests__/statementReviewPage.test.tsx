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
        <button type="button" onClick={() => onConfirm("review reason")}>Confirm {confirmLabel || "Confirm"}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
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
    let reviewCallCount = 0
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [] })
      }
      reviewCallCount++
      if (reviewCallCount === 1) return Promise.reject(new Error("review failed"))
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("Failed to load statement")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
  })

  it("AC16.18.5 disables approve when balance validation fails", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve({
        ...reviewData,
        balance_validation_result: {
          ...reviewData.balance_validation_result,
          closing_match: false,
          closing_delta: "12.00",
        },
      })
    })

    render(<StatementReviewPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    const approveButton = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement
    expect(approveButton.disabled).toBe(true)
    expect(approveButton.getAttribute("title")).toBe("Balance validation failed - cannot approve")
  })

  it("AC16.18.6 approve and reject call APIs and navigate", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve(reviewData)
    })

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


  it("prev/next navigation: renders navigation buttons with correct counter", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }] })
      }
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    expect(screen.getByText("2 / 3")).toBeInTheDocument()

    const prevButton = screen.getByTitle("Previous pending statement")
    const nextButton = screen.getByTitle("Next pending statement")
    expect((prevButton as HTMLButtonElement).disabled).toBe(false)
    expect((nextButton as HTMLButtonElement).disabled).toBe(false)
  })

  it("prev/next navigation: Prev navigates to previous statement", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }] })
      }
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    fireEvent.click(screen.getByTitle("Previous pending statement"))
    expect(pushMock).toHaveBeenCalledWith("/statements/s0/review")
  })

  it("prev/next navigation: Next navigates to next statement", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }] })
      }
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    fireEvent.click(screen.getByTitle("Next pending statement"))
    expect(pushMock).toHaveBeenCalledWith("/statements/s2/review")
  })

  it("prev/next navigation: Prev disabled on first statement, Next disabled on last", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [{ id: "s1" }] })
      }
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    const prevButton = screen.getByTitle("Previous pending statement") as HTMLButtonElement
    const nextButton = screen.getByTitle("Next pending statement") as HTMLButtonElement
    expect(prevButton.disabled).toBe(true)
    expect(nextButton.disabled).toBe(true)
  })

  it("balance validation: shows Valid indicator when closing_match is true", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    expect(screen.getByText("Valid")).toBeInTheDocument()
    expect(screen.getByText("✓")).toBeInTheDocument()
  })

  it("balance validation: shows Mismatch indicator with delta when closing_match is false", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve({
        ...reviewData,
        balance_validation_result: {
          ...reviewData.balance_validation_result,
          closing_match: false,
          closing_delta: "5.50",
        },
      })
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    expect(screen.getByText("✗")).toBeInTheDocument()
    expect(screen.getByText(/Mismatch/)).toBeInTheDocument()
    expect(screen.getByText(/5\.50/)).toBeInTheDocument()
  })

  it("renders PDF preview fallback and iframe when pdf_url present, and shows formatted amounts and transaction row", async () => {
    // first: pdf_url null (reviewData has pdf_url null)
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] })
      return Promise.resolve(reviewData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    // PDF preview fallback
    expect(screen.getByText("PDF preview not available")).toBeInTheDocument()

    // balance cards show formatted amounts (look for 1,000.00 / 1,500.00)
    const opens = screen.getAllByText(/1,000\.00/)
    expect(opens.length).toBeGreaterThanOrEqual(1)
    const closes = screen.getAllByText(/1,500\.00/)
    expect(closes.length).toBeGreaterThanOrEqual(1)

    // transaction row renders date, description, amount sign and confidence
    expect(screen.getByText("2026-01-05")).toBeInTheDocument()
    expect(screen.getByText("Salary")).toBeInTheDocument()
    // amount should include a + sign for IN and show 500.00
    const amountEl = screen.getByText((content) => content.includes("500.00") && content.includes("+"))
    expect(amountEl).toBeInTheDocument()
    const conf = screen.getByText("high")
    expect(conf.className).toContain("badge-success")

    // now test when pdf_url is present
    const pdfData = { ...reviewData, pdf_url: "https://example.com/s1.pdf" }
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] })
      return Promise.resolve(pdfData)
    })

    render(<StatementReviewPage />)
    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    const iframe = screen.getByTitle("Statement PDF preview") as HTMLIFrameElement
    expect(iframe).toBeInTheDocument()
    expect(iframe.getAttribute("src")).toBe("https://example.com/s1.pdf")
  })
})
