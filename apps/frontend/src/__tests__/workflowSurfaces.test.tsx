import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  WorkflowNotificationCenter,
  WorkflowStatusFeed,
} from "@/components/workflow/WorkflowNotifications"
import {
  fetchWorkflowEvents,
  fetchWorkflowStatus,
  updateWorkflowEventStatus,
} from "@/lib/api"
import type {
  WorkflowEventListResponse,
  WorkflowStatusResponse,
} from "@/lib/types"

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}))

vi.mock("@/lib/api", () => ({
  fetchWorkflowEvents: vi.fn(),
  fetchWorkflowStatus: vi.fn(),
  updateWorkflowEventStatus: vi.fn(),
}))

const statusNeedsAction: WorkflowStatusResponse = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 2, href: "/review" },
  report_readiness: { state: "blocked", blocking_count: 2, href: "/reports" },
  event_counts: { unread: 3, action_required: 2, blocked: 1 },
}

const statusEmpty: WorkflowStatusResponse = {
  primary_state: "empty",
  next_action: { type: "upload", count: 0, href: "/statements/upload" },
  report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
  event_counts: { unread: 0, action_required: 0, blocked: 0 },
}

const workflowEvents: WorkflowEventListResponse = {
  total: 4,
  items: [
    {
      id: "blocked-event",
      user_id: "user-1",
      occurred_at: "2026-06-03T08:00:00Z",
      family: "reconciliation.blocked",
      severity: "blocked",
      status: "unread",
      title: "Reconciliation blocked",
      summary: "Two transactions need matching before the report can be trusted.",
      source_type: "reconciliation",
      source_id: "source-1",
      action_href: "/reconciliation/unmatched",
      report_impact: "blocked",
      dedupe_key: "event:blocked",
      created_at: "2026-06-03T08:00:00Z",
      updated_at: "2026-06-03T08:00:00Z",
    },
    {
      id: "review-event",
      user_id: "user-1",
      occurred_at: "2026-06-03T07:00:00Z",
      family: "review.required",
      severity: "action_required",
      status: "unread",
      title: "Review required",
      summary: "A statement has low-confidence entries that need confirmation.",
      source_type: "bank_statement",
      source_id: "source-2",
      action_href: "/review",
      report_impact: "blocked",
      dedupe_key: "event:review",
      created_at: "2026-06-03T07:00:00Z",
      updated_at: "2026-06-03T07:00:00Z",
    },
    {
      id: "success-event",
      user_id: "user-1",
      occurred_at: "2026-06-03T06:00:00Z",
      family: "ledger.auto_posted",
      severity: "success",
      status: "read",
      title: "Safe entries posted",
      summary: "Automation posted high-confidence entries.",
      source_type: "journal",
      source_id: "source-3",
      action_href: "/journal",
      report_impact: "ready",
      dedupe_key: "event:success",
      created_at: "2026-06-03T06:00:00Z",
      updated_at: "2026-06-03T06:00:00Z",
    },
    {
      id: "info-event",
      user_id: "user-1",
      occurred_at: "2026-06-03T05:00:00Z",
      family: "source.uploaded",
      severity: "info",
      status: "read",
      title: "Statement uploaded",
      summary: "The file is queued for processing.",
      source_type: "bank_statement",
      source_id: "source-4",
      action_href: "/statements/source-4",
      report_impact: "processing",
      dedupe_key: "event:info",
      created_at: "2026-06-03T05:00:00Z",
      updated_at: "2026-06-03T05:00:00Z",
    },
  ],
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe("workflow notification surfaces", () => {
  beforeEach(() => {
    vi.mocked(fetchWorkflowStatus).mockReset()
    vi.mocked(fetchWorkflowEvents).mockReset()
    vi.mocked(updateWorkflowEventStatus).mockReset()
    vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusNeedsAction)
    vi.mocked(fetchWorkflowEvents).mockResolvedValue(workflowEvents)
    vi.mocked(updateWorkflowEventStatus).mockResolvedValue(workflowEvents.items[0])
  })

  it("AC19.3.4 shows the header badge from compact workflow counts and hides counts when quiet", async () => {
    renderWithQuery(<WorkflowNotificationCenter />)

    const button = await screen.findByRole("button", { name: /Workflow events/i })
    expect(button).toHaveTextContent("3")
    expect(button).toHaveAccessibleName(/2 actions/i)
    expect(button).toHaveAccessibleName(/1 blocked/i)
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1)

    vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusEmpty)
    renderWithQuery(<WorkflowNotificationCenter />)
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Workflow events/i })[1]).not.toHaveTextContent("0"))
  })

  it("AC19.3.5 groups inbox events by actionability and supports read/archive lifecycle actions", async () => {
    renderWithQuery(<WorkflowNotificationCenter />)

    fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i }))
    const dialog = await screen.findByRole("dialog", { name: "Workflow events" })

    expect(within(dialog).getByRole("heading", { name: "Blocked" })).toBeInTheDocument()
    expect(within(dialog).getByRole("heading", { name: "Action required" })).toBeInTheDocument()
    expect(within(dialog).getByRole("heading", { name: "Routine automation" })).toBeInTheDocument()
    expect(within(dialog).getByRole("link", { name: /Open Reconciliation blocked/i })).toHaveAttribute(
      "href",
      "/reconciliation/unmatched",
    )

    fireEvent.click(within(dialog).getByRole("button", { name: "Mark Reconciliation blocked as read" }))
    await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read"))

    fireEvent.click(within(dialog).getByRole("button", { name: "Archive Review required" }))
    await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("review-event", "archived"))
  })

  it("AC19.3.6 renders status feed severity, readiness, routine summary, and empty no-action state", () => {
    const { rerender } = render(<WorkflowStatusFeed status={statusNeedsAction} events={workflowEvents.items} />)

    expect(screen.getByRole("heading", { name: "Workflow status" })).toBeInTheDocument()
    expect(screen.getByText("Review required")).toBeInTheDocument()
    expect(screen.getByText("Report blocked")).toBeInTheDocument()
    expect(screen.getByText("Routine automation")).toBeInTheDocument()
    expect(screen.getByText("2 routine events")).toBeInTheDocument()
    expect(screen.queryByText(/audit/i)).not.toBeInTheDocument()

    rerender(<WorkflowStatusFeed status={statusEmpty} events={[]} />)
    expect(screen.getByText("No action required")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Upload statements" })).toHaveAttribute("href", "/statements/upload")
  })
})
