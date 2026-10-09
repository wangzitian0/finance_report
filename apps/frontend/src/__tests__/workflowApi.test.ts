import { beforeEach, describe, expect, it, vi } from "vitest"

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value
    },
    removeItem: (key: string) => {
      delete store[key]
    },
    clear: () => {
      store = {}
    },
  }
})()

function makeFetchMock(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
    headers: { get: () => null },
  })
}

describe("workflow API helpers", () => {
  beforeEach(() => {
    vi.resetModules()
    localStorageMock.clear()
    vi.unstubAllGlobals()
    vi.stubGlobal("localStorage", localStorageMock)
  })

  // AC-platform.fe-workflow.1
  it("AC19.3.3 fetches typed workflow status through lib/api-client.ts", async () => {
    const fetchMock = makeFetchMock(200, {
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
    })
    vi.stubGlobal("fetch", fetchMock)

    const { apiOperation } = await import("@/lib/api-client")
    const status = await apiOperation("get_workflow_status_endpoint_workflow_status_get")

    expect(status.primary_state).toBe("needs_action")
    expect(status.next_action.label).toBe("Review required")
    expect(status.event_counts.action_required).toBe(2)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/workflow/status"),
      expect.objectContaining({ headers: expect.any(Object) }),
    )
  })

  it("AC19.3.3 fetches events with bounded limit and patches lifecycle state", async () => {
    const fetchMock = makeFetchMock(200, { items: [], total: 0 })
    vi.stubGlobal("fetch", fetchMock)

    const { apiOperation } = await import("@/lib/api-client")
    await apiOperation("list_workflow_events_endpoint_workflow_events_get", {
      query: { status: "unread", limit: 20 },
    })
    await apiOperation(
      "update_workflow_event_status_endpoint_workflow_events__event_id__patch",
      {
        path: { event_id: "event-1" },
        body: { status: "archived" },
      },
    )

    expect(fetchMock.mock.calls[0][0]).toContain("/api/workflow/events")
    expect(fetchMock.mock.calls[0][0]).toContain("status=unread")
    expect(fetchMock.mock.calls[0][0]).toContain("limit=20")
    expect(fetchMock.mock.calls[1][0]).toContain("/api/workflow/events/event-1")
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "archived" }),
      }),
    )
  })
})
