import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import Stage2ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, children }: { isOpen: boolean; onConfirm: (note?: string) => void; onCancel: () => void; children?: ReactNode }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("resolution note")}>Confirm Resolve</button>
        <button onClick={onCancel}>Cancel Resolve</button>
        {children}
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const queuePayload = {
  pending_matches: [
    { id: "m1", match_score: 88, status: "pending_review", created_at: "2026-01-01T00:00:00Z" },
    { id: "m2", match_score: 70, status: "pending_review", created_at: "2026-01-02T00:00:00Z" },
  ],
  consistency_checks: [
    {
      id: "c1",
      check_type: "duplicate",
      status: "pending",
      related_txn_ids: ["t1"],
      details: { message: "Duplicate transaction" },
      severity: "high",
      resolved_at: null,
      resolution_note: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  has_unresolved_checks: true,
}

describe("Stage2ReviewQueuePage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  it("AC16.17.1 shows failure fallback and supports retry", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("queue failed")).mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Failed to load review queue")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByText("Stage 2 Review Queue")).toBeInTheDocument())
  })

  it("AC16.17.2 shows unresolved-check warning and disables batch approval", async () => {
    mockedApiFetch.mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Unresolved consistency checks block batch approval")).toBeInTheDocument())
    const approveButton = screen.getByRole("button", { name: "Approve Selected" })
    expect((approveButton as HTMLButtonElement).disabled).toBe(true)
    expect(approveButton.getAttribute("title")).toBe("Resolve consistency checks first")
  })

  it("AC16.17.3 performs batch reject and approve workflows", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })
      .mockResolvedValueOnce({ success: true, rejected_count: 1 })
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })
      .mockResolvedValueOnce({ success: true, approved_count: 2 })
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Stage 2 Review Queue")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/batch-reject-matches", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1", "m2"] }),
      }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Approve Selected" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/batch-approve-matches", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1", "m2"] }),
      }),
    )
  })

  it("AC16.17.4 resolves consistency checks through dialog actions", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(queuePayload)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" }).at(-1) as HTMLButtonElement)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/consistency-checks/c1/resolve", {
        method: "POST",
        body: JSON.stringify({ action: "reject", note: undefined }),
      }),
    )
  })
})
