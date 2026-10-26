// #2583 S4 — the shell polls /workflow/status on every page. Each call costs the server about
// 1.7 s at one year of data, so the poll slows down when no work is pending.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WORKFLOW_STATUS_POLL_IDLE_MS,
  WORKFLOW_STATUS_POLL_PENDING_MS,
  WORKFLOW_STATUS_QUERY_KEY,
  useWorkflowStatusQuery,
  workflowStatusHasPendingWork,
} from "@/hooks/useWorkflowStatus";
import { apiOperation } from "@/lib/api-client";
import type { WorkflowStatusResponse } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

function status(overrides: Partial<WorkflowStatusResponse> = {}): WorkflowStatusResponse {
  return {
    primary_state: "ready",
    next_action: { type: "open_report", count: 1, href: "/reports/package", label: "Open report", summary: "Ready." },
    report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
    event_counts: { unread: 0, action_required: 0, blocked: 0 },
    active_session: null,
    ...overrides,
  } as WorkflowStatusResponse;
}

const ACTIVE_SESSION = {
  id: "11111111-1111-4111-8111-111111111111",
  status: "active",
  title: "Upload-to-report session",
  summary: "Current work.",
  started_at: "2026-10-21T00:00:00Z",
  last_event_at: "2026-10-21T00:05:00Z",
  source_count: 1,
  primary_state: "ready",
  report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" },
  event_counts: { unread: 0, action_required: 0, blocked: 0 },
} as unknown as WorkflowStatusResponse["active_session"];

function wrapperFor(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function statusReads() {
  return mockedApiOperation.mock.calls.length;
}

describe("workflow status polling (#2583 S4)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedApiOperation.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // AC-reporting.fe-fetch-budget.6
  it.each([
    ["an active session", status({ active_session: ACTIVE_SESSION })],
    ["a processing (parsing) state", status({ primary_state: "processing" })],
    ["an action-required state", status({ primary_state: "needs_action" })],
    ["a blocked state", status({ primary_state: "blocked" })],
    ["an action-required event", status({ event_counts: { unread: 0, action_required: 1, blocked: 0 } })],
    ["a blocked event", status({ event_counts: { unread: 0, action_required: 0, blocked: 1 } })],
  ])("AC-reporting.fe-fetch-budget.6 polls every 30 s while the status shows %s", async (_label, pending) => {
    mockedApiOperation.mockResolvedValue(pending);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(statusReads()).toBe(1));

    await advance(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(2);
    await advance(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(3);
  });

  // AC-reporting.fe-fetch-budget.6
  it("AC-reporting.fe-fetch-budget.6 polls every 120 s while nothing is pending", async () => {
    mockedApiOperation.mockResolvedValue(status());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(statusReads()).toBe(1));

    await advance(WORKFLOW_STATUS_POLL_PENDING_MS * 3);
    expect(statusReads()).toBe(1);
    await advance(WORKFLOW_STATUS_POLL_IDLE_MS - WORKFLOW_STATUS_POLL_PENDING_MS * 3);
    expect(statusReads()).toBe(2);
  });

  // AC-reporting.fe-fetch-budget.6
  it("AC-reporting.fe-fetch-budget.6 changes its pace when the status changes", async () => {
    mockedApiOperation.mockResolvedValueOnce(status({ primary_state: "processing" }));
    mockedApiOperation.mockResolvedValue(status());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(statusReads()).toBe(1));

    // First status is pending work: the next read comes after 30 s and answers "ready".
    await advance(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(2);
    // Now idle: 30 s later there is no new read.
    await advance(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(2);
    await advance(WORKFLOW_STATUS_POLL_IDLE_MS - WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(3);
  });

  // AC-reporting.fe-fetch-budget.6
  it("AC-reporting.fe-fetch-budget.6 keeps the refetch on window focus", async () => {
    mockedApiOperation.mockResolvedValue(status());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useWorkflowStatusQuery(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(statusReads()).toBe(1));

    const observer = client.getQueryCache().find({ queryKey: WORKFLOW_STATUS_QUERY_KEY })?.observers[0];
    expect(observer?.options.refetchOnWindowFocus).toBe(true);
  });

  // AC-reporting.fe-fetch-budget.6
  it("AC-reporting.fe-fetch-budget.6 treats a missing status as pending work", () => {
    expect(workflowStatusHasPendingWork(undefined)).toBe(true);
    expect(workflowStatusHasPendingWork(status())).toBe(false);
  });

  // AC-reporting.fe-fetch-budget.6
  it("AC-reporting.fe-fetch-budget.6 treats a payload without the status fields as pending work and does not throw", async () => {
    // Mocked and degraded backends answer `{}`. The interval callback runs in the shell on every page.
    expect(workflowStatusHasPendingWork({} as WorkflowStatusResponse)).toBe(true);

    mockedApiOperation.mockResolvedValue({});
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderHook(() => useWorkflowStatusQuery(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(statusReads()).toBe(1));
    await advance(WORKFLOW_STATUS_POLL_PENDING_MS);
    expect(statusReads()).toBe(2);
    expect(view.result.current.isError).toBe(false);
  });
});
