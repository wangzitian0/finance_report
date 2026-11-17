import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  WORKFLOW_STATUS_POLL_IDLE_MS,
  WORKFLOW_STATUS_POLL_PENDING_MS,
  WORKFLOW_STATUS_QUERY_KEY,
  WORKFLOW_STATUS_STALE_MS,
  useWorkflowStatusQuery,
  workflowStatusHasPendingWork,
} from "@/hooks/useWorkflowStatus"; import { WorkflowNotificationCenter, WorkflowNotices, WorkflowInbox, WorkflowStatusFeed, } from "@/components/workflow/WorkflowNotifications"; import { humanizeWorkflowText } from "@/components/workflow/workflowFormat"; import { apiOperation } from "@/lib/api"; import type { WorkflowEventListResponse, WorkflowStatusResponse, } from "@/lib/types"; import { createInvalidationProbe } from "./fixtures/invalidationProbe"; vi.mock("next/link", () => ({ default: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) => ( <a href={href} {...props}>
{children}
</a> ), })); const fetchWorkflowStatus = vi.fn(); const fetchWorkflowEvents = vi.fn(); const updateWorkflowEventStatus = vi.fn(); vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(async (operationId: string, request: any = {}) => { if (operationId === "get_workflow_status_endpoint_workflow_status_get") { return fetchWorkflowStatus() }; if (operationId === "list_workflow_events_endpoint_workflow_events_get") { return fetchWorkflowEvents() }; if (operationId === "update_workflow_event_status_endpoint_workflow_events__event_id__patch") { return updateWorkflowEventStatus(request?.path?.event_id, request?.body?.status) }; throw new Error(`Unexpected apiOperation call: ${operationId}`) }), })); const statusNeedsAction: WorkflowStatusResponse = { primary_state: "needs_action", next_action: { type: "review_required", count: 2, href: "/inbox", label: "Review required", summary: "Confirm the source or review item so trusted report preparation can continue.", }, report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 }, active_session: { id: "session-1", status: "active", title: "Upload-to-report session", summary: "Current upload, processing, review, and report-readiness work.", started_at: "2026-06-03T05:00:00Z", last_event_at: "2026-06-03T08:00:00Z", source_count: 4, primary_state: "needs_action", report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 }, }, }; const statusEmpty: WorkflowStatusResponse = { primary_state: "empty", next_action: { type: "upload", count: 0, href: "/upload", label: "Upload statements", summary: "Add source documents to start the upload-to-report workflow.", }, report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 }, }; const makeWfEvent = (id: string, severity: string, status: string, title: string, summary: string, source_type: string, action_href: string, report_impact: string, extra: Record<string, unknown> = {}) => ({ id, user_id: "user-1", session_id: "session-1", occurred_at: "2026-06-03T08:00:00Z", family: `${source_type}.${severity}`, severity, status, title, summary, source_type, source_id: id, action_href, report_impact, dedupe_key: `event:${id}`, created_at: "2026-06-03T08:00:00Z", updated_at: "2026-06-03T08:00:00Z", ...extra, }); const workflowEvents: WorkflowEventListResponse = { total: 4, items: [ makeWfEvent("blocked-event", "blocked", "unread", "Reconciliation blocked", "Two transactions need matching before the report can be trusted.", "reconciliation", "/reconciliation?tab=unmatched", "blocked") as any, makeWfEvent("review-event", "action_required", "unread", "Review required", "A statement has low-confidence entries that need confirmation.", "bank_statement", "/inbox", "blocked") as any, makeWfEvent("success-event", "success", "read", "Safe entries posted", "Automation posted high-confidence entries.", "journal", "/journal", "ready") as any, makeWfEvent("info-event", "info", "read", "Statement uploaded", "The file is queued for processing.", "bank_statement", "/statements/source-4", "processing") as any, ], sessions: [statusNeedsAction.active_session!], }; function renderWithQuery(ui: ReactNode) { const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } }, }); return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>) }; describe("workflow notification surfaces", () => { beforeEach(() => { vi.mocked(fetchWorkflowStatus).mockReset(); vi.mocked(fetchWorkflowEvents).mockReset(); vi.mocked(updateWorkflowEventStatus).mockReset(); vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusNeedsAction); vi.mocked(fetchWorkflowEvents).mockResolvedValue(workflowEvents); vi.mocked(updateWorkflowEventStatus).mockResolvedValue(workflowEvents.items[0]) }); it("AC19.3.4 AC22.2.3 shows the header badge from compact workflow counts and hides counts when quiet", async () => { renderWithQuery(<WorkflowNotificationCenter />); const button = await screen.findByRole("button", { name: /Workflow events/i }); await waitFor(() => expect(button).toHaveTextContent("3")); await waitFor(() => expect(button).toHaveAccessibleName(/2 actions/i)); expect(button).toHaveAccessibleName(/1 blocked/i); expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1); vi.mocked(fetchWorkflowStatus).mockResolvedValue(statusEmpty)
renderWithQuery(<WorkflowNotificationCenter />); await waitFor(() => expect(screen.getAllByRole("button", { name: /Workflow events/i })[1]).not.toHaveTextContent("0")) }); it("AC22.6.3 links the notification center to the full confidence-ranked attention queue", async () => { renderWithQuery(<WorkflowNotificationCenter />); fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i })); const dialog = await screen.findByRole("dialog", { name: "Workflow events" }); const link = within(dialog).getByRole("link", { name: /needs confirmation/i }); expect(link).toHaveAttribute("href", "/audit?tab=needs-you"); fireEvent.click(link); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Workflow events" })).not.toBeInTheDocument()) }); it("AC19.3.5 AC19.8.4 groups inbox events by workflow session timeline and supports lifecycle actions", async () => { renderWithQuery(<WorkflowNotificationCenter />); fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i })); const dialog = await screen.findByRole("dialog", { name: "Workflow events" }); await waitFor(() => expect(within(dialog).getByRole("heading", { name: "Upload-to-report session" })).toBeInTheDocument()); expect(within(dialog).getByRole("list", { name: "Upload-to-report session timeline" })).toBeInTheDocument(); expect(within(dialog).getAllByRole("link", { name: "Open Reconciliation blocked" })[0]).toHaveAttribute( "href", "/reconciliation?tab=unmatched", ); fireEvent.click(within(dialog).getAllByRole("button", { name: "Mark as read" })[0]); await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read")); fireEvent.click(within(dialog).getAllByRole("button", { name: "Archive" })[1]); await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("review-event", "archived")); fireEvent.click(within(dialog).getByRole("button", { name: "Close panel" })); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Workflow events" })).not.toBeInTheDocument()) }); it("AC-testing.fe-async.2 event lifecycle flow invalidates the matrix-declared query keys against a real QueryClient", async () => { const probe = createInvalidationProbe("workflow.event-lifecycle"); render(<WorkflowNotificationCenter />, { wrapper: probe.wrapper }); fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i })); const dialog = await screen.findByRole("dialog", { name: "Workflow events" }); await waitFor(() => expect(within(dialog).getAllByRole("button", { name: "Mark as read" }).length).toBeGreaterThan(0), )
probe.expectNothingInvalidated(); fireEvent.click(within(dialog).getAllByRole("button", { name: "Mark as read" })[0]); await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read")); await waitFor(() => probe.expectDeclaredInvalidated()) }); it("AC19.3.5 shows drawer event load failures without hiding status", async () => { vi.mocked(fetchWorkflowEvents).mockRejectedValue(new Error("events unavailable"))
renderWithQuery(<WorkflowNotificationCenter />); fireEvent.click(await screen.findByRole("button", { name: /Workflow events/i })); const dialog = await screen.findByRole("dialog", { name: "Workflow events" }); expect(await within(dialog).findByText("Unable to load workflow events.")).toBeInTheDocument(); expect(within(dialog).getByText("Upload-to-report session")).toBeInTheDocument() }); it("AC19.8.4 groups legacy events without session metadata into a fallback session", async () => { const onStatusChange = vi.fn(); const legacyEvents = workflowEvents.items.map((event) => ({ ...event, session_id: null })); render(<WorkflowInbox events={legacyEvents} sessions={[]} onStatusChange={onStatusChange} />); expect(screen.getByRole("heading", { name: "Workflow session" })).toBeInTheDocument(); expect(screen.getByText("Legacy workflow events without a stored session.")).toBeInTheDocument(); expect(screen.getByText("4 events")).toBeInTheDocument(); expect(screen.getByRole("list", { name: "Workflow session timeline" })).toBeInTheDocument(); fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]); expect(onStatusChange).toHaveBeenCalledWith("blocked-event", "read") }); it("AC19.8.4 derives legacy fallback session copy for action-only, routine-only, and empty inboxes", () => { const actionOnlyEvents = workflowEvents.items .filter((event) => event.severity === "action_required") .map((event) => ({ ...event, session_id: null })); const routineOnlyEvents = workflowEvents.items .filter((event) => event.severity === "success" || event.severity === "info") .map((event) => ({ ...event, session_id: null })); const { rerender } = render(<WorkflowInbox events={actionOnlyEvents} sessions={[]} />); expect(screen.getByText("1 event")).toBeInTheDocument(); expect(screen.getByRole("list", { name: "Workflow session timeline" })).toBeInTheDocument()
rerender(<WorkflowInbox events={routineOnlyEvents} sessions={[]} />); expect(screen.getByText("2 events")).toBeInTheDocument()
rerender(<WorkflowInbox events={[]} sessions={[]} />); expect(screen.getByText("Workflow events will appear here when review or blockers need attention.")).toBeInTheDocument() }); it("AC19.3.6 renders status feed severity, readiness, routine summary, and empty no-action state", () => { const { rerender } = render(<WorkflowStatusFeed status={statusNeedsAction} events={workflowEvents.items} />); expect(screen.getByRole("heading", { name: "Workflow status" })).toBeInTheDocument(); expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1); expect(screen.getByText("Report blocked")).toBeInTheDocument(); expect(screen.getByText("Routine automation")).toBeInTheDocument(); expect(screen.getByText("2 routine events")).toBeInTheDocument(); expect(screen.queryByText(/audit/i)).not.toBeInTheDocument()
rerender(<WorkflowStatusFeed status={statusEmpty} events={[]} />); expect(screen.getByText("No action required")).toBeInTheDocument(); expect(screen.getByRole("link", { name: "Upload statements" })).toHaveAttribute("href", "/upload") }); it("AC19.12.5 renders lightweight derived workflow events as user actions, not internal logs", () => { render(<WorkflowStatusFeed status={statusNeedsAction} events={workflowEvents.items} />); expect(screen.getAllByText("Reconciliation blocked").length).toBeGreaterThanOrEqual(1); expect(screen.getAllByText("Review required").length).toBeGreaterThanOrEqual(1); expect(screen.getByRole("heading", { name: "Routine automation" })).toBeInTheDocument(); expect(screen.getByText("2 routine events")).toBeInTheDocument(); expect(screen.queryByText(/raw audit/i)).not.toBeInTheDocument(); expect(screen.queryByText(/journal line id/i)).not.toBeInTheDocument() }); it("AC-platform.fe-workflow.8 requests upload-page workflow events in parallel with the status", async () => { vi.mocked(fetchWorkflowStatus).mockReturnValue(new Promise<WorkflowStatusResponse>(() => {}))
renderWithQuery(<WorkflowNotices />); await waitFor(() => expect(fetchWorkflowEvents).toHaveBeenCalledTimes(1)); expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1); expect(screen.getByText("Loading workflow status...")).toBeInTheDocument() }); it("AC8.13.92 status feed falls back to the generic workflow action label for unknown next actions", () => { render( <WorkflowStatusFeed
status={{ primary_state: "ready", next_action: { type: "unknown" as WorkflowStatusResponse["next_action"]["type"], count: 0, href: "/inbox", label: "", summary: "" }, report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 }, }}
events={[]}
/>, ); expect(screen.getByRole("link", { name: "Open workflow" })).toHaveAttribute("href", "/inbox") }); it("AC19.4.8 keeps legacy next-action type fallbacks when label is absent", () => { const fallbackCases: Array<[ WorkflowStatusResponse["next_action"]["type"], string, string, ]> = [ ["upload", "Upload statements", "/upload"], ["review_required", "Review required", "/inbox"], ["resolve_blocker", "Resolve blocker", "/reconciliation?tab=unmatched"], ["open_report", "Open report package", "/reports/package"], ["wait", "View processing", "/inbox"], ]; const makeStatus = ( type: WorkflowStatusResponse["next_action"]["type"], href: string, ): WorkflowStatusResponse => ({ primary_state: type === "upload" ? "empty" : "needs_action", next_action: { type, count: 0, href, label: "", summary: "", }, report_readiness: { state: "processing", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 }, }); const { rerender } = render(<WorkflowStatusFeed status={makeStatus("upload", "/upload")} events={[workflowEvents.items[3]]} />); for (const [type, label, href] of fallbackCases) { rerender(<WorkflowStatusFeed status={makeStatus(type, href)} events={[workflowEvents.items[3]]} />); expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href) } }); it("AC19.3.5 renders the upload-page notices loading and unavailable states", async () => { vi.mocked(fetchWorkflowStatus).mockImplementation(() => new Promise(() => undefined)); vi.mocked(fetchWorkflowEvents).mockImplementation(() => new Promise(() => undefined)); const { unmount } = renderWithQuery(<WorkflowNotices />); expect(screen.getByText("Loading workflow status...")).toBeInTheDocument(); expect(screen.queryByRole("heading", { name: "Workflow events" })).not.toBeInTheDocument()
unmount(); vi.mocked(fetchWorkflowStatus).mockRejectedValue(new Error("status unavailable")); vi.mocked(fetchWorkflowEvents).mockRejectedValue(new Error("events unavailable"))
renderWithQuery(<WorkflowNotices />); expect(await screen.findByText("Workflow status is unavailable.")).toBeInTheDocument(); expect(screen.queryByText("Loading workflow status...")).not.toBeInTheDocument() }); it("AC19.3.5 renders the upload-page status feed, inbox total, and lifecycle actions", async () => { renderWithQuery(<WorkflowNotices />); expect(await screen.findByRole("heading", { name: "Workflow status" })).toBeInTheDocument(); expect(screen.getByText("4 total")).toBeInTheDocument(); expect(screen.getByRole("heading", { name: "Workflow events" })).toBeInTheDocument(); expect(screen.getByRole("heading", { name: "Upload-to-report session" })).toBeInTheDocument(); expect(screen.getAllByRole("link", { name: "Open Reconciliation blocked" })[0]).toHaveAttribute( "href", "/reconciliation?tab=unmatched", ); fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]); await waitFor(() => expect(updateWorkflowEventStatus).toHaveBeenCalledWith("blocked-event", "read")) }); it("AC-platform.fe-workflow.9 folds the upload-page notices under one summary line", async () => { renderWithQuery(<WorkflowNotices />); const notices = await screen.findByTestId("upload-workflow-summary"); expect(notices.tagName).toBe("DETAILS"); expect(notices).not.toHaveAttribute("open"); const summary = notices.querySelector("summary"); expect(summary).toHaveTextContent("Workflow: Needs Action · 1 blocker · 2 actions · 4 events"); expect(summary).toHaveTextContent("Show details"); expect(summary).not.toContainElement(screen.getByRole("heading", { name: "Workflow status" })) }); it("humanizeWorkflowText replaces all five invariant jargon patterns and preserves ordinary copy", () => { expect( humanizeWorkflowText( "Package section invariant failed: opening_balance_missing, cash_balance_input_missing, cash_identity_missing", ), ).toBe("Upload a bank statement to verify opening and ending cash balances."); expect(humanizeWorkflowText("Package section invariant failed: opening_balance_missing")).toBe( "Opening balance awaits bank statement verification.", ); expect(humanizeWorkflowText("Package section invariant failed: cash_balance_input_missing")).toBe( "Ending cash balance awaits bank statement verification.", ); expect(humanizeWorkflowText("Package section invariant failed: cash_identity_missing")).toBe( "Cash account balance awaits bank statement verification.", ); expect(humanizeWorkflowText("Package section invariant failed")).toBe("Statement balance check needed"); expect(humanizeWorkflowText("Ordinary user-facing summary")).toBe("Ordinary user-facing summary"); expect(humanizeWorkflowText(undefined)).toBe(""); expect(humanizeWorkflowText(null)).toBe("") }) })

function pollStatus(overrides: Partial<WorkflowStatusResponse> = {}): WorkflowStatusResponse {
  return {
    primary_state: "ready",
    next_action: { type: "open_report", count: 1, href: "/reports/package", label: "Open report", summary: "Ready." },
    report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
    event_counts: { unread: 0, action_required: 0, blocked: 0 },
    active_session: null,
    ...overrides,
  } as WorkflowStatusResponse;
}
function pollWrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}
async function advanceTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
describe("workflow status polling (#2583 S4)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchWorkflowStatus.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });
  it.each([
    ["an active session", pollStatus({ active_session: statusNeedsAction.active_session })],
    ["a processing (parsing) state", pollStatus({ primary_state: "processing" })],
    ["an action-required state", pollStatus({ primary_state: "needs_action" })],
    ["a blocked state", pollStatus({ primary_state: "blocked" })],
    ["an action-required event", pollStatus({ event_counts: { unread: 0, action_required: 1, blocked: 0 } })],
    ["a blocked event", pollStatus({ event_counts: { unread: 0, action_required: 0, blocked: 1 } })],
  ])("AC-reporting.fe-fetch-budget.6 polls every 30 s while the status shows %s", async (_label, pending) => {
    fetchWorkflowStatus.mockResolvedValue(pending);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: pollWrapperFor(client) });
    await waitFor(() => expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1));
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(2);
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(3);
  });
  it("AC-reporting.fe-fetch-budget.6 polls every 120 s while nothing is pending", async () => {
    fetchWorkflowStatus.mockResolvedValue(pollStatus());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: pollWrapperFor(client) });
    await waitFor(() => expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1));
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS * 3);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1);
    await advanceTimers(WORKFLOW_STATUS_POLL_IDLE_MS - WORKFLOW_STATUS_POLL_PENDING_MS * 3);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(2);
  });
  it("AC-reporting.fe-fetch-budget.6 changes its pace when the status changes", async () => {
    fetchWorkflowStatus.mockResolvedValueOnce(pollStatus({ primary_state: "processing" }));
    fetchWorkflowStatus.mockResolvedValue(pollStatus());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: pollWrapperFor(client) });
    await waitFor(() => expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1));
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(2);
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(2);
    await advanceTimers(WORKFLOW_STATUS_POLL_IDLE_MS - WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(3);
  });
  it("AC-reporting.fe-fetch-budget.6 keeps window-focus refetch and sets staleTime cache window", async () => {
    fetchWorkflowStatus.mockResolvedValue(pollStatus());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = pollWrapperFor(client);
    const first = renderHook(() => useWorkflowStatusQuery(), { wrapper });
    await waitFor(() => expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1));
    const observer = client.getQueryCache().find({ queryKey: WORKFLOW_STATUS_QUERY_KEY })?.observers[0];
    expect(observer?.options.refetchOnWindowFocus).toBe(true);
    expect(observer?.options.staleTime).toBe(WORKFLOW_STATUS_STALE_MS);
    first.unmount();
    renderHook(() => useWorkflowStatusQuery(), { wrapper });
    await advanceTimers(100);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1);
  });
  it("AC-reporting.fe-fetch-budget.6 treats missing or incomplete payloads as pending without throwing", async () => {
    expect(workflowStatusHasPendingWork(undefined)).toBe(true);
    expect(workflowStatusHasPendingWork(pollStatus())).toBe(false);
    expect(workflowStatusHasPendingWork({} as WorkflowStatusResponse)).toBe(true);
    fetchWorkflowStatus.mockResolvedValue({});
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderHook(() => useWorkflowStatusQuery(), { wrapper: pollWrapperFor(client) });
    await waitFor(() => expect(fetchWorkflowStatus).toHaveBeenCalledTimes(1));
    await advanceTimers(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(fetchWorkflowStatus).toHaveBeenCalledTimes(2);
    expect(view.result.current.isError).toBe(false);
  });
}); // AC-platform.fe-ia-inbox.2 AC-platform.fe-ia-inbox.6 AC-platform.fe-workflow.2 AC-platform.fe-workflow.3 AC-platform.fe-workflow.6 AC-platform.fe-workflow.7 AC-reporting.fe-fetch-budget.6
