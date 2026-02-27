import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import StatementsPage from "@/app/(main)/statements/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

vi.mock("@/components/statements/StatementUploader", () => ({
  default: ({ onUploadComplete }: { onUploadComplete: () => void }) => (
    <button onClick={onUploadComplete}>UploadMock</button>
  ),
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("StatementsPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    vi.stubGlobal("confirm", vi.fn(() => true))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("AC16.14.10 renders loading, error, empty, and populated states", async () => {
    mockedApiFetch
      .mockRejectedValueOnce(new Error("load failed"))
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({
        items: [
          {
            id: "s1",
            original_filename: "stmt.pdf",
            institution: "DBS",
            status: "approved",
            period_start: "2026-01-01",
            period_end: "2026-01-31",
            currency: "SGD",
            confidence_score: 90,
            transactions: [],
            opening_balance: 100,
            closing_balance: 200,
            balance_validated: true,
            validation_error: null,
          },
        ],
      })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getAllByText("load failed")).toHaveLength(2))
    fireEvent.click(screen.getByRole("button", { name: "Retry loading statements" }))
    await waitFor(() => expect(screen.getByText("No statements uploaded yet")).toBeInTheDocument())
    fireEvent.click(screen.getByText("UploadMock"))
    await waitFor(() => expect(screen.getByText("stmt.pdf")).toBeInTheDocument())
  })

  it("AC16.14.11 enables polling when parsing statements exist", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        {
          id: "s2",
          original_filename: "parsing.pdf",
          institution: "DBS",
          status: "parsing",
          period_start: null,
          period_end: null,
          currency: null,
          confidence_score: null,
          transactions: [],
          opening_balance: null,
          closing_balance: null,
          balance_validated: null,
          validation_error: null,
        },
      ],
    })
    const intervalSpy = vi.spyOn(globalThis, "setInterval")

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("AI Parsing in Progress")).toBeInTheDocument())
    expect(intervalSpy).toHaveBeenCalled()
  })

  it("AC16.14.12 delete action calls delete API and toast", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "s3",
            original_filename: "delete.pdf",
            institution: "DBS",
            status: "approved",
            period_start: "2026-01-01",
            period_end: "2026-01-31",
            currency: "SGD",
            confidence_score: 88,
            transactions: [],
            opening_balance: 50,
            closing_balance: 70,
            balance_validated: true,
            validation_error: null,
          },
        ],
      })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ items: [] })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("delete.pdf")).toBeInTheDocument())
    fireEvent.click(screen.getByTitle("Delete Statement"))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s3", { method: "DELETE" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Statement deleted successfully", "success")
  })
})
