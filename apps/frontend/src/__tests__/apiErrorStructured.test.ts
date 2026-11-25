import { afterEach, beforeEach, expect, it, vi } from "vitest";
const stubFetch = (status: number, body: unknown) =>
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        text: () =>
          Promise.resolve(
            typeof body === "string" ? body : JSON.stringify(body),
          ),
        json: () => Promise.resolve(body),
        headers: { get: () => null },
      }),
  );
beforeEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});
afterEach(() => vi.unstubAllGlobals());
it.each([
  [
    409,
    { error_id: "conflict", detail: "Blocked", request_id: "req-123" },
    "conflict",
    "req-123",
    "Blocked",
  ],
  [
    422,
    JSON.stringify({
      detail: [{ loc: ["query", "x"], msg: "field required", type: "missing" }],
    }),
    null,
    null,
    null,
  ],
  [500, "plain text failure", null, null, "plain text failure"],
] as const)(
  "test_AC12_27_3 status=%d",
  async (status, body, errorId, requestId, msg) => {
    stubFetch(status, body);
    const { apiOperation, ApiError } = await import("../lib/api");
    let caught: unknown;
    try {
      await apiOperation("batch_update_matches_reconciliation_matches_post", {
        body: { action: "accept", match_ids: [] },
      });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const err = caught as InstanceType<typeof ApiError>;
    expect([err.status, err.errorId, err.requestId]).toEqual([
      status,
      errorId,
      requestId,
    ]);
    expect(err.message).not.toContain("[object Object]");
    expect(err.message).toBe(msg ?? body);
  },
);
// AC-meta.fe-http-client.22 AC12.27.3 test_AC12_27_3_api_error_carries_error_id
