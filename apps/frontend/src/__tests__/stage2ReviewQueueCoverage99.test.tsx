import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Stage2ReviewQueue } from "@/components/review/Stage2ReviewQueue"
import { apiFetch } from "@/lib/api"

import { renderReviewComponent } from "./helpers/renderReviewComponent"

const navState = vi.hoisted(() => ({
  pathname: "/reconciliation/review-queue",
  replace: vi.fn(),
  push: vi.fn(),
  searchParams: new URLSearchParams(),
}))

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navState.replace, push: navState.push }),
  useSearchParams: () => navState.searchParams,
  usePathname: () => navState.pathname,
}))

const mockedApiFetch = vi.mocked(apiFetch)

const pendingMatch = {
  id: "m1",
  match_score: 88,
  status: "pending_review",
  created_at: "2026-01-01T00:00:00Z",
  description: "Salary transfer",
  amount: 1200,
  txn_date: "2026-01-01",
}

const lowMatch = {
  id: "m2",
  match_score: 55,
  status: "pending_review",
  created_at: "2026-01-02T00:00:00Z",
  description: "Low confidence transfer",
  amount: null,
  txn_date: null,
}

const duplicateCheck = {
  id: "c1",
  check_type: "duplicate",
  status: "pending",
  related_txn_ids: [],
  details: { message: "Potential duplicate" },
  severity: "high",
  resolved_at: null,
  resolution_note: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

const customCheck = {
  id: "c2",
  check_type: "manual_review",
  status: "pending",
  related_txn_ids: [],
  details: { reason: "Needs human review" },
  severity: "low",
  resolved_at: null,
  resolution_note: null,
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
}

function queue(overrides: Partial<{
  pending_matches: unknown[]
  consistency_checks: unknown[]
  has_unresolved_checks: boolean
}> = {}) {
  return {
    pending_matches: [pendingMatch],
    consistency_checks: [],
    has_unresolved_checks: false,
    ...overrides,
  }
}

describe("AC8.13.48 Stage2ReviewQueue frontend coverage lift", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset()
    navState.pathname = "/reconciliation/review-queue"
    navState.searchParams = new URLSearchParams()
    navState.replace.mockReset()
    navState.push.mockReset()
  })

  it("test_AC8_13_48_run_review_approves_matches_after_filter_changes", async () => {
    navState.pathname = "/review/run/run%201"
    navState.searchParams = new URLSearchParams("check_type=duplicate&status=pending&severity=high,medium&min_score=60")

    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch, lowMatch], consistency_checks: [] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [] } as never)
      }
      if (path === "/api/statements/batch-approve-matches") {
        expect(options).toMatchObject({
          method: "POST",
          body: JSON.stringify({ match_ids: ["m1", "m2"] }),
        })
        return Promise.resolve({ success: true, approved_count: 2 } as never)
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)

    expect(await screen.findByText("Stage 2 Run Review")).toBeInTheDocument()
    expect(screen.getByText("run 1")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "HIGH" }))
    const [checkTypeSelect, statusSelect] = screen.getAllByRole("combobox")
    fireEvent.change(checkTypeSelect, { target: { value: "anomaly" } })
    fireEvent.change(statusSelect, { target: { value: "resolved" } })

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Deselect all" }))
    await waitFor(() => expect(screen.getByText("0 selected")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Approve Run" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/statements/batch-approve-matches",
        expect.objectContaining({ method: "POST" }),
      )
    })
    expect(navState.replace).toHaveBeenCalled()
  })

  it("test_AC8_13_48_dialog_dismissal_and_resolution_error_paths", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ consistency_checks: [customCheck], has_unresolved_checks: true }) as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.reject(new Error("filter failed"))
      }
      if (path === "/api/statements/consistency-checks/c2/resolve") {
        return Promise.reject(new Error("resolve failed"))
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)

    expect(await screen.findByText("manual_review")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))
    expect(await screen.findByRole("dialog", { name: "Resolve Consistency Check" })).toBeInTheDocument()

    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))
    const overlay = document.querySelector("[aria-hidden='true']") as HTMLElement
    fireEvent.click(overlay)
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))
    const dialog = await screen.findByRole("dialog", { name: "Resolve Consistency Check" })
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Keep reviewing" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/statements/consistency-checks/c2/resolve",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ action: "reject", note: "Keep reviewing" }),
        }),
      )
    })

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument())
  })

  it("test_AC8_13_48_batch_and_run_error_branches_surface_actionable_feedback", async () => {
    navState.pathname = "/review/run/run-2"

    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch], consistency_checks: [] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [] } as never)
      }
      if (path === "/api/statements/batch-approve-matches") {
        return Promise.resolve({ success: false, error: "approval rejected by server" } as never)
      }
      if (path === "/api/statements/batch-reject-matches") {
        return Promise.reject(new Error("batch reject failed"))
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)

    expect(await screen.findByText("Stage 2 Run Review")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Approve Selected" }))
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/statements/batch-approve-matches",
        expect.objectContaining({ method: "POST" }),
      )
    })

    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/statements/batch-reject-matches",
        expect.objectContaining({ method: "POST" }),
      )
    })

    fireEvent.click(screen.getByRole("button", { name: "Approve Run" }))
    await waitFor(() => {
      const approveCalls = mockedApiFetch.mock.calls.filter((call) => call[0] === "/api/statements/batch-approve-matches")
      expect(approveCalls.length).toBeGreaterThanOrEqual(2)
    })
  })

  it("test_AC8_13_48_filters_checks_and_toggles_individual_match_selection", async () => {
    navState.pathname = "/review/run/run-3"

    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch], consistency_checks: [duplicateCheck, customCheck] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.reject(new Error("processing summary failed"))
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [duplicateCheck, customCheck] } as never)
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)

    expect(await screen.findByText("Stage 2 Run Review")).toBeInTheDocument()
    expect(await screen.findByText("manual_review")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "HIGH" }))
    await waitFor(() => expect(screen.queryByText("manual_review")).not.toBeInTheDocument())
    expect(screen.getAllByText("Duplicate").length).toBeGreaterThan(0)

    fireEvent.click(screen.getByText("Salary transfer"))
    await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Salary transfer"))
    await waitFor(() => expect(screen.getByText("0 selected")).toBeInTheDocument())
  })

  it("test_AC8_13_48_run_approval_guard_states_explain_disabled_actions", async () => {
    navState.pathname = "/review/run/run-4"

    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch], consistency_checks: [duplicateCheck], has_unresolved_checks: true }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [duplicateCheck] } as never)
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    const first = renderReviewComponent(<Stage2ReviewQueue />)
    const unresolvedButton = await screen.findByRole("button", { name: "Approve Run" })
    expect(unresolvedButton).toBeDisabled()
    expect(unresolvedButton).toHaveAttribute("title", "Resolve consistency checks first")
    first.unmount()

    mockedApiFetch.mockReset()
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch], consistency_checks: [] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 1, pending_total: "10", currency: "SGD", oldest_pending_date: "2026-01-01" } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [] } as never)
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    const second = renderReviewComponent(<Stage2ReviewQueue />)
    const processingButton = await screen.findByRole("button", { name: "Approve Run" })
    expect(processingButton).toBeDisabled()
    expect(processingButton).toHaveAttribute("title", "Clear Processing Account pending transfers first")
    second.unmount()

    mockedApiFetch.mockReset()
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [], consistency_checks: [] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [] } as never)
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)
    const emptyButton = await screen.findByRole("button", { name: "Approve Run" })
    expect(emptyButton).toBeDisabled()
    expect(emptyButton).toHaveAttribute("title", "No pending matches remain")
  })

  it("test_AC8_13_48_run_approval_network_errors_are_reported", async () => {
    navState.pathname = "/review/run/run-5"

    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/statements/stage2/queue") {
        return Promise.resolve(queue({ pending_matches: [pendingMatch], consistency_checks: [] }) as never)
      }
      if (path === "/api/accounts/processing/summary") {
        return Promise.resolve({ pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null } as never)
      }
      if (path.startsWith("/api/statements/consistency-checks/list")) {
        return Promise.resolve({ items: [] } as never)
      }
      if (path === "/api/statements/batch-approve-matches") {
        return Promise.reject(new Error("approve run failed"))
      }
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })

    renderReviewComponent(<Stage2ReviewQueue />)

    fireEvent.click(await screen.findByRole("button", { name: "Approve Run" }))
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/statements/batch-approve-matches",
        expect.objectContaining({ method: "POST" }),
      )
    })
    expect(await screen.findByText("approve run failed")).toBeInTheDocument()
  })
})
