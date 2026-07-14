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
  it("AC19.3.3 fetches typed workflow status through lib/api.ts", async () => {
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

    const { fetchWorkflowStatus } = await import("@/lib/api")
    const status = await fetchWorkflowStatus()

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

    const { fetchWorkflowEvents, updateWorkflowEventStatus } = await import("@/lib/api")
    await fetchWorkflowEvents({ status: "unread", limit: 20 })
    await updateWorkflowEventStatus("event-1", "archived")

    expect(fetchMock.mock.calls[0][0]).toContain("/api/workflow/events?status=unread&limit=20")
    expect(fetchMock.mock.calls[1][0]).toContain("/api/workflow/events/event-1")
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "archived" }),
      }),
    )
  })
})
