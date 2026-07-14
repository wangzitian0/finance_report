import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReconciliationWorkbench from "@/components/reconciliation/Workbench"
import { apiFetch } from "@/lib/api"

import { createInvalidationProbe } from "./fixtures/invalidationProbe"

const navigationState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigationState.searchParams,
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
    navigationState.searchParams = new URLSearchParams()
  })

  const statsResponse = {
    total_transactions: 5,
    matched_transactions: 2,
    unmatched_transactions: 3,
    pending_review: 2,
    auto_accepted: 1,
    match_rate: 40,
    score_distribution: { high: 1, medium: 2, low: 2 },
  }

  const matchResponse = {
    id: "m1",
    match_score: 85,
    status: "pending_review",
    transaction: { id: "t1", description: "Rent", txn_date: "2026-01-02", direction: "OUT", amount: 800 },
    entries: [{ id: "e1", memo: "Rent", entry_date: "2026-01-02", total_amount: 800 }],
    score_breakdown: { amount: 50, date: 20, description: 15 },
  }

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
    await waitFor(() => expect(screen.getAllByText("Transfer").length).toBeGreaterThan(0))
    await waitFor(() => expect(screen.getByText("Score 88")).toBeInTheDocument())
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
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/runs", { method: "POST", body: JSON.stringify({}) }))

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

  it("AC16.20.6 score distribution renders 0% height for buckets with value 0", async () => {
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
          score_distribution: { "90-100": 5, "80-89": 0, "60-79": 2, "0-59": 0 },
        })
      }
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Score Distribution")).toBeInTheDocument())
    // Wait for the distribution bucket labels to be rendered (only present when stats is loaded)
    await waitFor(() => expect(screen.getByText("90-100")).toBeInTheDocument())
    // Buckets with value 0 must render height: 0%
    const allDivs = Array.from(document.querySelectorAll("[style]"))
    const zeroBars = allDivs.filter((el) => (el as HTMLElement).style.height === "0%")
    expect(zeroBars.length).toBeGreaterThanOrEqual(2)
    // Non-zero buckets must have height > 0%
    const nonZeroBars = allDivs.filter((el) => {
      const h = (el as HTMLElement).style.height
      return h.endsWith("%") && h !== "0%"
    })
    expect(nonZeroBars.length).toBeGreaterThanOrEqual(2)
  })

  it("test_AC8_13_48 surfaces query failures for stats and pending matches", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) {
        return Promise.reject(new Error("stats down"))
      }
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.resolve({ items: [] })
      }
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    expect(await screen.findByText("Failed to load reconciliation stats: stats down")).toBeInTheDocument()

    mockedApiFetch.mockReset()
    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) {
        return Promise.resolve(statsResponse)
      }
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.reject(new Error("pending down"))
      }
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    expect(await screen.findByText("Failed to load pending matches: pending down")).toBeInTheDocument()
  })

  it("test_AC8_13_48 reports mutation failures without dropping the review queue", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) return Promise.resolve(statsResponse)
      if (url.includes("/api/reconciliation/pending")) return Promise.resolve({ items: [matchResponse] })
      if (url.includes("/api/reconciliation/transactions/t1/anomalies")) return Promise.resolve([])
      if (url.includes("/api/reconciliation/runs")) return Promise.reject(new Error("run failed"))
      if (url.includes("/api/reconciliation/batch-accept")) return Promise.reject(new Error("batch failed"))
      if (url.includes("/api/reconciliation/matches/m1/accept")) return Promise.reject(new Error("accept failed"))
      if (url.includes("/api/reconciliation/matches/m1/reject")) return Promise.reject(new Error("reject failed"))
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Rent")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Run Matching" }))
    expect(await screen.findByText("run failed")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 80" }))
    expect(await screen.findByText("Batch accept failed: batch failed")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    expect(await screen.findByText("Failed to accept match: accept failed")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    expect(await screen.findByText("Failed to reject match: reject failed")).toBeInTheDocument()
  })

  it("test_AC8_13_48 refreshes an existing selection and clears it when the queue becomes empty", async () => {
    const pendingResponses = [
      { items: [matchResponse] },
      {
        items: [
          {
            ...matchResponse,
            transaction: { ...matchResponse.transaction, amount: 825 },
            score_breakdown: { amount: 55, date: 20, description: 10 },
          },
        ],
      },
      { items: [] },
    ]

    mockedApiFetch.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) return Promise.resolve(statsResponse)
      if (url.includes("/api/reconciliation/pending")) return Promise.resolve(pendingResponses.shift() ?? { items: [] })
      if (url.includes("/api/reconciliation/transactions/t1/anomalies")) return Promise.resolve([])
      if (url.includes("/api/reconciliation/runs")) return Promise.resolve({})
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getAllByText("800.00").length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole("button", { name: "Run Matching" }))
    await waitFor(() => expect(screen.getByText("825.00")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Run Matching" }))
    await waitFor(() => expect(screen.getByText("No pending matches")).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText("Select a match to review")).toBeInTheDocument())
  })

})

// #1827 G-async-seam: each mutating Workbench flow is exercised separately
// against a real QueryClient so removing any single invalidateQueries call
// reds exactly its own test. Only the network fn apiFetch is mocked.
describe("Workbench invalidation matrix flows (#1827 G-async-seam)", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    navigationState.searchParams = new URLSearchParams()
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
  })

  async function renderWithProbe(flow: string) {
    const probe = createInvalidationProbe(flow)
    render(<ReconciliationWorkbench />, { wrapper: probe.wrapper })
    await waitFor(() => expect(screen.getByText("Rent")).toBeInTheDocument())
    probe.expectNothingInvalidated()
    return probe
  }

  it("AC-testing.fe-async.2 run-matching flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.run")
    fireEvent.click(screen.getByRole("button", { name: "Run Matching" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/runs", {
        method: "POST",
        body: JSON.stringify({}),
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 accept-match flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.accept-match")
    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/matches/m1/accept", { method: "POST" }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 reject-match flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.reject-match")
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/matches/m1/reject", { method: "POST" }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 batch-accept flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.batch-accept")
    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 80" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/batch-accept", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1"] }),
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })
})
