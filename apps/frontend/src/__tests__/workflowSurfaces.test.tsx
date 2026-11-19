import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WORKFLOW_STATUS_POLL_IDLE_MS, WORKFLOW_STATUS_POLL_PENDING_MS, WORKFLOW_STATUS_QUERY_KEY, WORKFLOW_STATUS_STALE_MS, useWorkflowStatusQuery, workflowStatusHasPendingWork } from "@/hooks/useWorkflowStatus";
import { WorkflowInbox, WorkflowNotificationCenter, WorkflowNotices, WorkflowStatusFeed } from "@/components/workflow/WorkflowNotifications";
import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import { createInvalidationProbe } from "./fixtures/invalidationProbe";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
const fSt = vi.fn(), fEv = vi.fn(), upd = vi.fn();
vi.mock("@/lib/api", () => ({
  apiOperation: vi.fn(async (op: string, r: { path?: { event_id?: string }; body?: { status?: string } } = {}) =>
    op.includes("status_get") ? fSt() : op.includes("events_get") ? fEv() : upd(r?.path?.event_id, r?.body?.status)),
}));

describe("workflow notification surfaces", () => {
  beforeEach(() => { fSt.mockReset(); fEv.mockReset(); upd.mockReset(); fSt.mockResolvedValue(F.WF_ST_ACT); fEv.mockResolvedValue(F.WF_EVS); upd.mockResolvedValue(F.WF_EVS.items[0]); });

  it("AC19.3.4 AC22.2.3 AC22.6.3 AC19.3.5 AC19.8.4 notification center & invalidation", () =>
    F.assertWfNotifCenter(fSt, fEv, upd, WorkflowNotificationCenter, createInvalidationProbe("workflow.event-lifecycle")));
  it("AC19.8.4 AC19.3.6 AC19.12.5 AC8.13.92 AC19.4.8 WorkflowInbox & WorkflowStatusFeed", () =>
    F.assertWfInboxAndFeed(WorkflowInbox as never, WorkflowStatusFeed as never));
  it("AC-platform.fe-workflow.8 AC-platform.fe-workflow.9 AC19.3.5 WorkflowNotices & humanizeWorkflowText", () =>
    F.assertWfNoticesHumanize(fSt, fEv, upd, WorkflowNotices, humanizeWorkflowText));
});

describe("workflow status polling (#2583 S4)", () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); fSt.mockReset(); });
  afterEach(() => { vi.useRealTimers(); });

  it.each(F.WF_POLL_CASES)("AC-reporting.fe-fetch-budget.6 polls 30s for %s", async (_l, mk) => {
    fSt.mockResolvedValue(mk()); renderHook(() => useWorkflowStatusQuery());
    await waitFor(() => expect(fSt).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(WORKFLOW_STATUS_POLL_PENDING_MS); });
    expect(fSt).toHaveBeenCalledTimes(2);
  });

  it("AC-reporting.fe-fetch-budget.6 adapts poll interval, caches staleTime, handles empty", () =>
    F.assertWfPollingAdaptive(fSt, useWorkflowStatusQuery as never, workflowStatusHasPendingWork, WORKFLOW_STATUS_QUERY_KEY, WORKFLOW_STATUS_STALE_MS, WORKFLOW_STATUS_POLL_PENDING_MS, WORKFLOW_STATUS_POLL_IDLE_MS));
}); // AC-platform.fe-ia-inbox.2 AC-platform.fe-ia-inbox.6 AC-platform.fe-workflow.2 AC-platform.fe-workflow.3 AC-platform.fe-workflow.6 AC-platform.fe-workflow.7 AC-reporting.fe-fetch-budget.6
