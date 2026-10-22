import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReconciliationWorkbench from "@/components/reconciliation/Workbench"
import { apiOperation } from "@/lib/api-client"

import { createInvalidationProbe } from "./fixtures/invalidationProbe"

const navigationState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock("@/components/reconciliation/UnmatchedBoard", () => ({
  default: () => <div>Mock Unmatched Board</div>,
}))

vi.mock("@/components/review/Stage2ReviewQueue", () => ({
  Stage2ReviewQueue: () => <div>Mock Review Queue</div>,
}))

function mapWorkbenchOperationToLegacy(operationId: string, req: any = {}): [string, RequestInit | undefined] {
  switch (operationId) {
    case "reconciliation_stats_reconciliation_stats_get":
      return ["/api/reconciliation/stats", undefined];
    case "pending_review_queue_reconciliation_pending_get":
      return ["/api/reconciliation/pending", undefined];
    case "list_anomalies_reconciliation_transactions__txn_id__anomalies_get":
      return [`/api/reconciliation/transactions/${req?.path?.txn_id}/anomalies`, undefined];
    case "run_reconciliation_reconciliation_runs_post":
      return ["/api/reconciliation/runs", { method: "POST", body: JSON.stringify(req?.body ?? {}) }];
    case "batch_accept_reconciliation_batch_accept_post":
      return ["/api/reconciliation/batch-accept", { method: "POST", body: JSON.stringify(req?.body) }];
    case "accept_match_reconciliation_matches__match_id__accept_post":
      return [`/api/reconciliation/matches/${req?.path?.match_id}/accept`, { method: "POST" }];
    case "reject_match_reconciliation_matches__match_id__reject_post":
      return [`/api/reconciliation/matches/${req?.path?.match_id}/reject`, { method: "POST" }];
    default:
      return [operationId, req];
  }
}

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigationState.searchParams,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/reconciliation",
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
  const mockedApiOperation = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiOperation.mockReset()
    const originalMockImplementation = mockedApiOperation.mockImplementation.bind(mockedApiOperation)
    mockedApiOperation.mockImplementation = (fn: any) => {
      return originalMockImplementation((operationId: any, req: any) => {
        if (typeof operationId === "string" && operationId.startsWith("/")) {
          return fn(operationId, req)
        }
        const [path, options] = mapWorkbenchOperationToLegacy(operationId, req)
        return fn(path, options)
      })
    }
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

  // AC-reconciliation.fe-stage2-review.7
  it("AC16.20.1 loads stats and pending queue with default selection", async () => {
    mockedApiOperation.mockImplementation((path: string) => {
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

  // AC-reconciliation.fe-stage2-review.8
  it("AC16.20.2 triggers run, batch, accept, and reject APIs", async () => {
    mockedApiOperation.mockImplementation((path: string) => {
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
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("run_reconciliation_reconciliation_runs_post", { body: {} }))

    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 85" }))
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("batch_accept_reconciliation_batch_accept_post", {
        body: { match_ids: ["m1"] },
      }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("accept_match_reconciliation_matches__match_id__accept_post", { path: { match_id: "m1" } }))

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("reject_match_reconciliation_matches__match_id__reject_post", { path: { match_id: "m1" } }))
  })

  // AC-reconciliation.fe-stage2-review.11
  it("AC16.20.6 score distribution renders 0% height for buckets with value 0", async () => {
    mockedApiOperation.mockImplementation((path: string) => {
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
    mockedApiOperation.mockImplementation((path: string) => {
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

    mockedApiOperation.mockReset()
    mockedApiOperation.mockImplementation((path: string) => {
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
    mockedApiOperation.mockImplementation((path: string) => {
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

    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 85" }))
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

    mockedApiOperation.mockImplementation((path: string) => {
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

  it("renders workspace mode switcher and links selected match transaction to its source statement", async () => {
    mockedApiOperation.mockImplementation((path: string) => {
      const url = String(path)
      if (url.includes("/api/reconciliation/stats")) return Promise.resolve(statsResponse)
      if (url.includes("/api/reconciliation/pending")) {
        return Promise.resolve({
          items: [
            {
              ...matchResponse,
              transaction: {
                ...matchResponse.transaction,
                statement_id: "stmt-42",
                statement_filename: "dbs-2026-01.pdf",
              },
            },
            {
              ...matchResponse,
              id: "m2",
              transaction: {
                ...matchResponse.transaction,
                id: "t2",
                description: "Utilities",
              },
            },
          ],
        })
      }
      if (url.includes("/api/reconciliation/transactions/")) return Promise.resolve([])
      return Promise.resolve({})
    })

    render(<ReconciliationWorkbench />, { wrapper: createWrapper() })

    const workspaceNav = await screen.findByRole("navigation", {
      name: "Reconciliation workspace views",
    })
    const matchedTab = within(workspaceNav).getByRole("link", { name: "Matches" })
    expect(matchedTab).toHaveAttribute("href", "/reconciliation")
    expect(matchedTab).toHaveAttribute("aria-current", "page")

    const unmatchedTab = within(workspaceNav).getByRole("link", {
      name: /Unmatched/i,
    })
    expect(unmatchedTab).toHaveAttribute("href", "/reconciliation?tab=unmatched")
    expect(await within(unmatchedTab).findByText("3")).toBeInTheDocument()

    const reviewQueueTab = within(workspaceNav).getByRole("link", { name: "Review queue" })
    expect(reviewQueueTab).toHaveAttribute("href", "/reconciliation?tab=review-queue")

    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: "View source statement (dbs-2026-01.pdf)" }),
      ).toHaveAttribute("href", "/statements/stmt-42"),
    )

    fireEvent.click(screen.getByRole("button", { name: /Utilities/i }))
    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: "View source statement" }),
      ).toHaveAttribute("href", "/upload"),
    )
  })

})

// #1827 G-async-seam: each mutating Workbench flow is exercised separately
// against a real QueryClient so removing any single invalidateQueries call
// reds exactly its own test. Only the network fn apiFetch is mocked.
describe("Workbench invalidation matrix flows (#1827 G-async-seam)", () => {
  const mockedApiOperation = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiOperation.mockReset()
    const originalMockImplementation = mockedApiOperation.mockImplementation.bind(mockedApiOperation)
    mockedApiOperation.mockImplementation = (fn: any) => {
      return originalMockImplementation((operationId: any, req: any) => {
        if (typeof operationId === "string" && operationId.startsWith("/")) {
          return fn(operationId, req)
        }
        const [path, options] = mapWorkbenchOperationToLegacy(operationId, req)
        return fn(path, options)
      })
    }
    navigationState.searchParams = new URLSearchParams()
    mockedApiOperation.mockImplementation((path: string) => {
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
      expect(mockedApiOperation).toHaveBeenCalledWith("run_reconciliation_reconciliation_runs_post", {
        body: {},
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 accept-match flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.accept-match")
    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("accept_match_reconciliation_matches__match_id__accept_post", {
        path: { match_id: "m1" },
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 reject-match flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.reject-match")
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("reject_match_reconciliation_matches__match_id__reject_post", {
        path: { match_id: "m1" },
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  it("AC-testing.fe-async.2 batch-accept flow invalidates the matrix-declared query keys", async () => {
    const probe = await renderWithProbe("reconciliation.batch-accept")
    fireEvent.click(screen.getByRole("button", { name: "Batch Accept ≥ 85" }))
    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("batch_accept_reconciliation_batch_accept_post", {
        body: { match_ids: ["m1"] },
      }),
    )
    await waitFor(() => probe.expectDeclaredInvalidated())
  })

  // AC-reconciliation.fe-tabs.1
  it("AC-reconciliation.fe-tabs.1 shows the tab that the tab query parameter names and links each tab to its URL", async () => {
    const cases: [string, RegExp, string][] = [
      ["", /Matches/, "Reconciliation Workbench"],
      ["tab=unmatched&statement_id=s1", /Unmatched/, "Mock Unmatched Board"],
      ["tab=review-queue&check_type=duplicate", /Review queue/, "Mock Review Queue"],
      ["tab=unknown", /Matches/, "Reconciliation Workbench"],
    ]
    for (const [query, activeTab, content] of cases) {
      navigationState.searchParams = new URLSearchParams(query)
      const { unmount } = render(<ReconciliationWorkbench />, { wrapper: createWrapper() })
      const nav = screen.getByRole("navigation", { name: "Reconciliation workspace views" })
      const links = within(nav).getAllByRole("link")
      expect(links.map((link) => link.getAttribute("href"))).toEqual([
        "/reconciliation",
        "/reconciliation?tab=unmatched",
        "/reconciliation?tab=review-queue",
      ])
      const current = links.filter((link) => link.getAttribute("aria-current") === "page")
      expect(current, `?${query} must mark one tab as current`).toHaveLength(1)
      expect(current[0]).toHaveTextContent(activeTab)
      expect(screen.getByText(content)).toBeInTheDocument()
      unmount()
    }
  })
})
