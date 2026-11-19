import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { API_URL, ApiError, apiOperation, apiOperationDownload, apiOperationStream, apiOperationUpload, resetRedirectGuard } from "./api";
import * as X from "../__tests__/helpers/shellTestFixtures";

const fetchMock = vi.fn(), mockLoc = { href: "", pathname: "/dashboard" };
global.fetch = fetchMock;
Object.defineProperty(window, "location", { value: mockLoc, writable: true, configurable: true });

describe("api client", () => {
  beforeEach(() => { resetRedirectGuard(); fetchMock.mockReset(); mockLoc.href = ""; mockLoc.pathname = "/dashboard"; });

  it("serializes path/query & rejects missing path params", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) });
    await apiOperation(X.OPS.DIV, { path: { ticker: "MSFT" }, query: { limit: 5, offset: undefined, filter: null, tag: ["a", "b"] } as never });
    E(fetchMock).toHaveBeenCalledWith(`${API_URL}/api/portfolio/MSFT/dividends?limit=5&tag=a&tag=b`, E.objectContaining({ method: "GET", credentials: "include" }));
    await E(apiOperation(X.OPS.DIV, { path: { ticker: undefined as never } })).rejects.toThrow("Missing OpenAPI path parameter: ticker");
  });

  it.each(X.API_STATUS_CASES)("status %i", async (status, text, msg, href) => {
    fetchMock.mockResolvedValueOnce({ ok: false, status, text: async () => text });
    await E(apiOperation(X.OPS.BASE_CURR)).rejects.toThrow(msg); E(mockLoc.href).toBe(href);
  });

  it("422 ApiError, SSR guard, redirect throw", () => X.runApi422AndGuards(fetchMock, apiOperation, ApiError, mockLoc));
  it("stream, upload, download", () => X.runApiClientStreamsCheck(fetchMock, apiOperationStream, apiOperationUpload, apiOperationDownload));
});
