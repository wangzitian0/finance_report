import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// localStorage mock (must be set before importing the api module).
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
vi.stubGlobal("localStorage", localStorageMock);

function makeFetchMock(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () =>
      Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    headers: { get: () => null },
  });
}

// AC12.27.3: the frontend apiFetch throws a typed ApiError carrying the parsed
// error_id, so callers branch on a machine-readable code instead of message text.
describe("structured ApiError (#1005)", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal("localStorage", localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal("localStorage", localStorageMock);
  });

  it("test_AC12_27_3_api_error_carries_error_id parses error_id from the body", async () => {
    const fetchMock = makeFetchMock(409, {
      error_id: "conflict",
      detail: "Cannot batch approve while there are unresolved consistency checks",
      request_id: "req-123",
    });
    vi.stubGlobal("fetch", fetchMock);

    const { apiFetch, ApiError, isApiErrorCode } = await import("../lib/api");

    await expect(apiFetch("/api/statements/batch-approve-matches")).rejects.toThrow(
      ApiError
    );

    let caught: unknown;
    try {
      await apiFetch("/api/statements/batch-approve-matches");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiErr = caught as InstanceType<typeof ApiError>;
    expect(apiErr.status).toBe(409);
    expect(apiErr.errorId).toBe("conflict");
    expect(apiErr.requestId).toBe("req-123");
    // Callers branch on the machine-readable code, not the message text.
    expect(isApiErrorCode(caught, "conflict")).toBe(true);
    expect(isApiErrorCode(caught, "not_found")).toBe(false);
  });

  it("test_AC12_27_3 does not stringify a non-string (422 array) detail", async () => {
    // FastAPI request-validation errors return `detail` as an array of objects.
    // The message must fall back to the raw text, never "[object Object]".
    const rawBody = JSON.stringify({
      detail: [{ loc: ["query", "x"], msg: "field required", type: "missing" }],
    });
    const fetchMock = makeFetchMock(422, rawBody);
    vi.stubGlobal("fetch", fetchMock);

    const { apiFetch, ApiError } = await import("../lib/api");

    let caught: unknown;
    try {
      await apiFetch("/api/test");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiErr = caught as InstanceType<typeof ApiError>;
    expect(apiErr.status).toBe(422);
    expect(apiErr.message).not.toContain("[object Object]");
    expect(apiErr.message).toBe(rawBody);
  });

  it("test_AC12_27_3 keeps message fallback when the body has no error_id", async () => {
    const fetchMock = makeFetchMock(500, "plain text failure");
    vi.stubGlobal("fetch", fetchMock);

    const { apiFetch, ApiError } = await import("../lib/api");

    let caught: unknown;
    try {
      await apiFetch("/api/test");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiErr = caught as InstanceType<typeof ApiError>;
    expect(apiErr.errorId).toBeNull();
    expect(apiErr.message).toBe("plain text failure");
  });
});
