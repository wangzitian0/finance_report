import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReconciliationWorkbench from "@/components/reconciliation/Workbench"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  const Wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return Wrapper
}

describe("ReconciliationWorkbench", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.20.1 loads stats and pending queue with default selection", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) {
        return Promise.resolve({
          total_transactions: 10,
          matched_transactions: 8,
          unmatched_transactions: 2,
          pending_review: 1,
          auto_accepted: 7,
          match_rate: 80,
          score_distribution: { "90-100": 4, "80-89": 3, "60-79": 2, "0-59": 1 },
        })
      }
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.resolve({
          items: [
            {
              id: "m1",
              match_score: 88,
              status: "pending_review",
              transaction: { id: "t1", description: "Transfer", txn_date: "2026-01-01", direction: "OUT", amount: 100 },
              entries: [{ id: "e1", memo: "Bank fee", entry_date: "2026-01-01", total_amount: 100 }],
              score_breakdown: { amount: 40, date: 30, description: 18 },
            },
          ],
        })
      }
      if (url.includes("/api/reconciliation/transactions/t1/anomalies")) {
        return Promise.resolve([{ anomaly_type: "spike", severity: "high", message: "Unusual amount" }])
      }
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Reconciliation Workbench")).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText("Transfer")).toBeInTheDocument())
    expect(screen.getByText("Score 88")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText("Anomaly Signals")).toBeInTheDocument())
  })

  it("AC16.20.2 triggers run, batch, accept, and reject APIs", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) {
        return Promise.resolve({
          total_transactions: 5,
          matched_transactions: 2,
          unmatched_transactions: 3,
          pending_review: 2,
          auto_accepted: 1,
          match_rate: 40,
          score_distribution: { high: 1, medium: 2, low: 2 },
        })
      }
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.resolve({
          items: [
            {
              id: "m1",
              match_score: 85,
              status: "pending_review",
              transaction: { id: "t1", description: "Rent", txn_date: "2026-01-02", direction: "OUT", amount: 800 },
              entries: [{ id: "e1", memo: "Rent", entry_date: "2026-01-02", total_amount: 800 }],
              score_breakdown: { amount: 50, date: 20, description: 15 },
            },
          ],
        })
      }
      if (url.includes("/api/reconciliation/transactions/t1/anomalies")) {
        return Promise.resolve([])
      }
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Rent")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Run Matching" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/run", { method: "POST", body: JSON.stringify({}) }))

    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 80" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/batch-accept", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1"] }),
      }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/matches/m1/accept", { method: "POST" }))

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/matches/m1/reject", { method: "POST" }))
  })
})
