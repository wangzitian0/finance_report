import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { AnchorHTMLAttributes, ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  WorkflowNotificationCenter,
  WorkflowEventsPageContent,
  WorkflowInbox,
  UploadToReportHome,
  WorkflowStatusFeed,
} from "@/components/workflow/WorkflowNotifications"
import {
  apiFetch,
  fetchWorkflowEvents,
  fetchWorkflowStatus,
  updateWorkflowEventStatus,
} from "@/lib/api"
import type {
  WorkflowEventListResponse,
  WorkflowStatusResponse,
} from "@/lib/types"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("@/lib/api", () => {
  const fetchWorkflowStatus = vi.fn()
  const fetchWorkflowEvents = vi.fn()
  const updateWorkflowEventStatus = vi.fn()
  const apiFetch = vi.fn((path: string, options: RequestInit = {}) => {
    if (path === "/api/workflow/status") return fetchWorkflowStatus()
    if (path.startsWith("/api/workflow/events?")) return fetchWorkflowEvents()
    const eventMatch = path.match(/^\/api\/workflow\/events\/([^/]+)$/)
    if (eventMatch && options.method === "PATCH") {
      const body = JSON.parse(String(options.body ?? "{}")) as { status?: string }
      return updateWorkflowEventStatus(eventMatch[1], body.status)
    }
    return Promise.reject(new Error(`Unexpected apiFetch call: ${path}`))
  })

  return {
    apiFetch,
    fetchWorkflowEvents,
    fetchWorkflowStatus,
    updateWorkflowEventStatus,
  }
})

const statusNeedsAction: WorkflowStatusResponse = {
  primary_state: "needs_action",
  next_action: {
    type: "review_required",
    count: 2,
    href: "/review",
    label: "Review required",
    summary: "Confirm the source or review item so trusted report preparation can continue.",
  },
  report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" },
  event_counts: { unread: 3, action_required: 2, blocked: 1 },
  active_session: {
    id: "session-1",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-03T05:00:00Z",
    last_event_at: "2026-06-03T08:00:00Z",
    source_count: 4,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" },
    event_counts: { unread: 3, action_required: 2, blocked: 1 },
  },
}

const statusEmpty: WorkflowStatusResponse = {
  primary_state: "empty",
  next_action: {
    type: "upload",
    count: 0,
    href: "/statements/upload",
    label: "Upload statements",
    summary: "Add source documents to start the upload-to-report workflow.",
  },
  report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" },
  event_counts: { unread: 0, action_required: 0, blocked: 0 },
}

const workflowEvents: WorkflowEventListResponse = {
  total: 4,
  items: [
    {
      id: "blocked-event",
      user_id: "user-1",
      session_id: "session-1",
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
      session_id: "session-1",
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
      session_id: "session-1",
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
      session_id: "session-1",
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
  sessions: [
    {
      id: "session-1",
      status: "active",
      title: "Upload-to-report session",
      summary: "Current upload, processing, review, and report-readiness work.",
      started_at: "2026-06-03T05:00:00Z",
      last_event_at: "2026-06-03T08:00:00Z",
      source_count: 4,
      primary_state: "needs_action",
      report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" },
      event_counts: { unread: 3, action_required: 2, blocked: 1 },
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
    vi.mocked(apiFetch).mockClear()
    vi.mocked(fetchWorkflowStatus).mockReset()
    vi.mocked(fetchWorkflowEvents).mockReset()
    vi.mocked(updateWorkflowEventStatus).mockReset()
    vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusNeedsAction)
    vi.mocked(fetchWorkflowEvents).mockResolvedValue(workflowEvents)
    vi.mocked(updateWorkflowEventStatus).mockResolvedValue(workflowEvents.items[0])
  })

  it("AC19.3.4 AC22.2.3 shows the header badge from compact workflow counts and hides counts when quiet", async () => {
    renderWithQuery(<WorkflowNotificationCenter />)

    const button = await screen.findByRole("button", { name: /Workflow events/i })
    await waitFor(() => expect(button).toHaveTextContent("3"))
    await waitFor(() => expect(button).toHaveAccessibleName(/2 actions/i))
    expect(button).toHaveAccessibleName(/1 blocked/i)
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1)

    vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusEmpty)
    renderWithQuery(<WorkflowNotificationCenter />)
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Workflow events/i })[1]).not.toHaveTextContent("0"))
  })

  it("AC22.6.3 links the notification center to the full confidence-ranked attention queue", async () => {
    renderWithQuery(<WorkflowNotificationCenter />)

    fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i }))
    const dialog = await screen.findByRole("dialog", { name: "Workflow events" })

    const link = within(dialog).getByRole("link", { name: /attention queue/i })
    expect(link).toHaveAttribute("href", "/attention")

    // Following the link closes the notification sheet.
    fireEvent.click(link)
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Workflow events" })).not.toBeInTheDocument())
  })

  it("AC19.3.5 AC19.8.4 groups inbox events by workflow session timeline and supports lifecycle actions", async () => {
    renderWithQuery(<WorkflowNotificationCenter />)

    fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i }))
    const dialog = await screen.findByRole("dialog", { name: "Workflow events" })

    await waitFor(() => expect(within(dialog).getByRole("heading", { name: "Upload-to-report session" })).toBeInTheDocument())
    expect(within(dialog).getByRole("list", { name: "Upload-to-report session timeline" })).toBeInTheDocument()
    expect(within(dialog).getAllByRole("link", { name: "Open Reconciliation blocked" })[0]).toHaveAttribute(
      "href",
      "/reconciliation/unmatched",
    )

    fireEvent.click(within(dialog).getAllByRole("button", { name: "Mark as read" })[0])
    await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read"))

    fireEvent.click(within(dialog).getAllByRole("button", { name: "Archive" })[1])
    await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("review-event", "archived"))

    fireEvent.click(within(dialog).getByRole("button", { name: "Close panel" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Workflow events" })).not.toBeInTheDocument())
  })

  it("AC19.3.5 shows drawer event load failures without hiding status", async () => {
    vi.mocked(fetchWorkflowEvents).mockRejectedValue(new Error("events unavailable"))
    renderWithQuery(<WorkflowNotificationCenter />)

    fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i }))
    const dialog = await screen.findByRole("dialog", { name: "Workflow events" })

    expect(await within(dialog).findByText("Unable to load workflow events.")).toBeInTheDocument()
    expect(within(dialog).getByText("Upload-to-report session")).toBeInTheDocument()
  })

  it("AC19.8.4 groups legacy events without session metadata into a fallback session", async () => {
    const onStatusChange = vi.fn()
    const legacyEvents = workflowEvents.items.map((event) => ({ ...event, session_id: null }))

    render(<WorkflowInbox events={legacyEvents} sessions={[]} onStatusChange={onStatusChange} />)

    expect(screen.getByRole("heading", { name: "Workflow session" })).toBeInTheDocument()
    expect(screen.getByText("Legacy workflow events without a stored session.")).toBeInTheDocument()
    expect(screen.getByText("4 events")).toBeInTheDocument()
    expect(screen.getByRole("list", { name: "Workflow session timeline" })).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0])
    expect(onStatusChange).toHaveBeenCalledWith("blocked-event", "read")
  })

  it("AC19.8.4 derives legacy fallback session copy for action-only, routine-only, and empty inboxes", () => {
    const actionOnlyEvents = workflowEvents.items
      .filter((event) => event.severity === "action_required")
      .map((event) => ({ ...event, session_id: null }))
    const routineOnlyEvents = workflowEvents.items
      .filter((event) => event.severity === "success" || event.severity === "info")
      .map((event) => ({ ...event, session_id: null }))

    const { rerender } = render(<WorkflowInbox events={actionOnlyEvents} sessions={[]} />)
    expect(screen.getByText("1 event")).toBeInTheDocument()
    expect(screen.getByRole("list", { name: "Workflow session timeline" })).toBeInTheDocument()

    rerender(<WorkflowInbox events={routineOnlyEvents} sessions={[]} />)
    expect(screen.getByText("2 events")).toBeInTheDocument()

    rerender(<WorkflowInbox events={[]} sessions={[]} />)
    expect(screen.getByText("Workflow events will appear here when review or blockers need attention.")).toBeInTheDocument()
  })

  it("AC19.3.6 renders status feed severity, readiness, routine summary, and empty no-action state", () => {
    const { rerender } = render(<WorkflowStatusFeed status={statusNeedsAction} events={workflowEvents.items} />)

    expect(screen.getByRole("heading", { name: "Workflow status" })).toBeInTheDocument()
    expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Report blocked")).toBeInTheDocument()
    expect(screen.getByText("Routine automation")).toBeInTheDocument()
    expect(screen.getByText("2 routine events")).toBeInTheDocument()
    expect(screen.queryByText(/audit/i)).not.toBeInTheDocument()

    rerender(<WorkflowStatusFeed status={statusEmpty} events={[]} />)
    expect(screen.getByText("No action required")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Upload statements" })).toHaveAttribute("href", "/statements/upload")
  })

  it("AC19.12.5 renders lightweight derived workflow events as user actions, not internal logs", () => {
    render(<WorkflowStatusFeed status={statusNeedsAction} events={workflowEvents.items} />)

    expect(screen.getAllByText("Reconciliation blocked").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole("heading", { name: "Routine automation" })).toBeInTheDocument()
    expect(screen.getByText("2 routine events")).toBeInTheDocument()
    expect(screen.queryByText(/raw audit/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/journal line id/i)).not.toBeInTheDocument()
  })

  it("AC19.4.2 renders the upload-to-report home as the first workflow entry surface", () => {
    render(<UploadToReportHome status={statusNeedsAction} events={workflowEvents.items} />)

    expect(screen.getByRole("region", { name: "Upload-to-report home" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Upload-to-report session" })).toBeInTheDocument()
    expect(screen.getByText("Review the required action so automation can continue.")).toBeInTheDocument()
    expect(screen.getByText(statusNeedsAction.next_action.summary)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /^Review required$/i })).toHaveAttribute("href", "/review")
    expect(screen.getByRole("link", { name: "Report readiness" })).toHaveAttribute("href", "/reports/package")
    expect(screen.getByRole("heading", { name: "Workflow status" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Blocked" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Action required" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Recent session timeline" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Routine automation" })).toBeInTheDocument()
    expect(screen.getByText("2 routine events")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Archive/i })).not.toBeInTheDocument()
  })

  it("AC19.4.3 keeps the upload-first CTA and quiet state aligned to workflow next action", () => {
    render(<UploadToReportHome status={statusEmpty} events={[]} />)

    expect(screen.getByText("Upload files to start the automated reporting workflow.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Upload statements/i })).toHaveAttribute("href", "/statements/upload")
    expect(screen.getAllByText("Report none")[0]).toBeInTheDocument()
    expect(screen.getByText("0 blockers")).toBeInTheDocument()
    expect(screen.getByText("No action required")).toBeInTheDocument()
    expect(screen.getByText("0 routine events")).toBeInTheDocument()
  })

  it("AC19.4.4 exposes ready, processing, and stale report readiness states above analytics", () => {
    const { rerender } = render(
      <UploadToReportHome
        status={{
          primary_state: "ready",
          next_action: {
            type: "open_report",
            count: 0,
            href: "/reports/package",
            label: "Open report package",
            summary: "Inspect the personal report package and its readiness evidence.",
          },
          report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
          event_counts: { unread: 0, action_required: 0, blocked: 0 },
        }}
        events={workflowEvents.items.slice(2)}
      />,
    )

    expect(screen.getByText("Reports are ready to inspect.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open report package/i })).toHaveAttribute("href", "/reports/package")
    expect(screen.getAllByText("Report ready")[0]).toBeInTheDocument()

    rerender(
      <UploadToReportHome
        status={{
          primary_state: "processing",
          next_action: {
            type: "wait",
            count: 0,
            href: "/events",
            label: "View processing",
            summary: "Automation is processing source files; open the session timeline for progress.",
          },
          report_readiness: { state: "processing", blocking_count: 0, href: "/reports/package" },
          event_counts: { unread: 1, action_required: 0, blocked: 0 },
        }}
        events={[workflowEvents.items[3]]}
      />,
    )

    expect(screen.getByText("Automation is processing uploaded source files.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /View processing/i })).toHaveAttribute("href", "/events")
    expect(screen.getAllByText("Report processing")[0]).toBeInTheDocument()

    rerender(
      <UploadToReportHome
        status={{
          primary_state: "blocked",
          next_action: {
            type: "resolve_blocker",
            count: 1,
            href: "/reconciliation/unmatched",
            label: "Resolve blocker",
            summary: "Resolve the blocking condition before the report package can be trusted.",
          },
          report_readiness: { state: "stale", blocking_count: 1, href: "/reports/package" },
          event_counts: { unread: 1, action_required: 0, blocked: 1 },
        }}
        events={[workflowEvents.items[0]]}
      />,
    )

    expect(screen.getByText("A blocker is holding report readiness.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Resolve blocker/i })).toHaveAttribute("href", "/reconciliation/unmatched")
    expect(screen.getAllByText("Report stale")[0]).toBeInTheDocument()
    expect(screen.getByText("1 blocker")).toBeInTheDocument()
  })

  it("AC19.4.8 AC19.12.5 does not duplicate the workflow-state sentence when next-action summary is absent", () => {
    render(
      <UploadToReportHome
        status={{
          primary_state: "ready",
          next_action: {
            type: "open_report",
            count: 0,
            href: "/reports/package",
            label: "Open report package",
            summary: "",
          },
          report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
          event_counts: { unread: 0, action_required: 0, blocked: 0 },
        }}
        events={[]}
      />,
    )

    expect(screen.getAllByText("Reports are ready to inspect.")).toHaveLength(1)
  })

  it("AC8.13.92 upload home falls back to the generic workflow action label for unknown next actions", () => {
    render(
      <UploadToReportHome
        status={{
          primary_state: "ready",
          next_action: {
            type: "unknown" as WorkflowStatusResponse["next_action"]["type"],
            count: 0,
            href: "/events",
            label: "",
            summary: "",
          },
          report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" },
          event_counts: { unread: 0, action_required: 0, blocked: 0 },
        }}
        events={[]}
      />,
    )

    expect(screen.getByRole("link", { name: "Open workflow" })).toHaveAttribute("href", "/events")
  })

  it("AC19.4.8 keeps legacy next-action type fallbacks when label is absent", () => {
    const fallbackCases: Array<[
      WorkflowStatusResponse["next_action"]["type"],
      string,
      string,
    ]> = [
      ["upload", "Upload statements", "/statements/upload"],
      ["review_required", "Review required", "/review"],
      ["resolve_blocker", "Resolve blocker", "/reconciliation/unmatched"],
      ["open_report", "Open report package", "/reports/package"],
      ["wait", "View processing", "/events"],
    ]

    const makeStatus = (
      type: WorkflowStatusResponse["next_action"]["type"],
      href: string,
    ): WorkflowStatusResponse => ({
      primary_state: type === "upload" ? "empty" : "needs_action",
      next_action: {
        type,
        count: 0,
        href,
        label: "",
        summary: "",
      },
      report_readiness: { state: "processing", blocking_count: 0, href: "/reports/package" },
      event_counts: { unread: 0, action_required: 0, blocked: 0 },
    })

    const { rerender } = render(<WorkflowStatusFeed status={makeStatus("upload", "/statements/upload")} events={[workflowEvents.items[3]]} />)

    for (const [type, label, href] of fallbackCases) {
      rerender(<WorkflowStatusFeed status={makeStatus(type, href)} events={[workflowEvents.items[3]]} />)
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href)
    }
  })

  it("AC19.3.5 renders the events page loading and unavailable states", async () => {
    vi.mocked(fetchWorkflowStatus).mockImplementation(() => new Promise(() => undefined))
    vi.mocked(fetchWorkflowEvents).mockImplementation(() => new Promise(() => undefined))

    const { unmount } = renderWithQuery(<WorkflowEventsPageContent />)

    expect(screen.getByRole("heading", { name: "Notifications" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Upload statements" })).toHaveAttribute("href", "/upload")
    expect(screen.getByText("Loading workflow status...")).toBeInTheDocument()
    expect(screen.getByText("Loading workflow events...")).toBeInTheDocument()

    unmount()

    vi.mocked(fetchWorkflowStatus).mockRejectedValue(new Error("status unavailable"))
    vi.mocked(fetchWorkflowEvents).mockRejectedValue(new Error("events unavailable"))

    renderWithQuery(<WorkflowEventsPageContent />)

    expect(await screen.findByText("Workflow status is unavailable.")).toBeInTheDocument()
    expect(await screen.findByText("Unable to load workflow events.")).toBeInTheDocument()
  })

  it("AC19.3.5 renders the events page status feed, inbox total, and lifecycle actions", async () => {
    renderWithQuery(<WorkflowEventsPageContent />)

    expect(await screen.findByRole("heading", { name: "Workflow status" })).toBeInTheDocument()
    expect(screen.getByText("Your action center — everything that needs your review across uploads, reconciliation, and reports.")).toBeInTheDocument()
    expect(screen.getByText("4 total")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Workflow events" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Upload-to-report session" })).toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: "Open Reconciliation blocked" })[0]).toHaveAttribute(
      "href",
      "/reconciliation/unmatched",
    )

    fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0])
    await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read"))
  })
})
