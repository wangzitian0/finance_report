import { beforeEach, expect, it, vi } from "vitest";
beforeEach(() => {
  vi.resetModules();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});
it("AC19.3.3 fetches workflow status, lists events, and patches lifecycle state", async () => {
  const body = {
    primary_state: "needs_action",
    next_action: {
      type: "review_required",
      count: 2,
      href: "/review",
      label: "Review required",
      summary: "Confirm.",
    },
    report_readiness: {
      state: "blocked",
      blocking_count: 2,
      href: "/reports/package",
    },
    event_counts: { unread: 3, action_required: 2, blocked: 1 },
    items: [],
    total: 0,
  };
  const fm = vi
    .fn()
    .mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify(body)),
      json: () => Promise.resolve(body),
      headers: { get: () => null },
    });
  vi.stubGlobal("fetch", fm);
  const { apiOperation } = await import("@/lib/api");
  const st = await apiOperation(
    "get_workflow_status_endpoint_workflow_status_get",
  );
  expect([
    st.primary_state,
    st.next_action.label,
    st.event_counts.action_required,
  ]).toEqual(["needs_action", "Review required", 2]);
  expect(fm).toHaveBeenCalledWith(
    expect.stringContaining("/api/workflow/status"),
    expect.objectContaining({ headers: expect.any(Object) }),
  );
  await apiOperation("list_workflow_events_endpoint_workflow_events_get", {
    query: { status: "unread", limit: 20 },
  });
  await apiOperation(
    "update_workflow_event_status_endpoint_workflow_events__event_id__patch",
    { path: { event_id: "event-1" }, body: { status: "archived" } },
  );
  expect(fm.mock.calls[1][0]).toContain("/api/workflow/events");
  expect(fm.mock.calls[1][0]).toContain("status=unread");
  expect(fm.mock.calls[1][0]).toContain("limit=20");
  expect(fm.mock.calls[2][0]).toContain("/api/workflow/events/event-1");
  expect(fm.mock.calls[2][1]).toEqual(
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ status: "archived" }),
    }),
  );
});
// AC-platform.fe-workflow.1
