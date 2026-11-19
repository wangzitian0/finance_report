import { afterEach, beforeEach, describe, expect as E, it, vi } from "vitest";
import { apiOperation, apiOperationDownload, apiOperationStream, apiOperationUpload, resetRedirectGuard } from "../lib/api";
import { API_FN_CASES, OPS, makeFetchMock, runApiFnWrappersCheck } from "./helpers/shellTestFixtures";

describe("apiFunctions", () => {
  beforeEach(() => { vi.unstubAllGlobals(); localStorage.clear(); resetRedirectGuard(); });
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  it("cookies without Auth & 204/JSON", async () => {
    localStorage.setItem("finance_access_token", "stale-jwt");
    const f = makeFetchMock(200, { id: "u1", email: "a@example.com" }); vi.stubGlobal("fetch", f);
    E(await apiOperation(OPS.ME)).toEqual({ id: "u1", email: "a@example.com" });
    E(f).toHaveBeenCalledWith(E.stringContaining("/api/auth/me"), E.objectContaining({ credentials: "include" }));
    E((f.mock.calls[0][1].headers as Record<string, string>).Authorization).toBeUndefined();
    vi.stubGlobal("fetch", makeFetchMock(204, null));
    E(await apiOperation(OPS.ACC_DEL, { path: { account_id: "test" } })).toBeUndefined();
  });

  it.each(API_FN_CASES)("op %s", async (op, req, method, urlRe, body) => {
    const f = makeFetchMock(200, body); vi.stubGlobal("fetch", f);
    E(await apiOperation(op as never, req as never)).toEqual(body);
    E(String(f.mock.calls[0][0])).toMatch(urlRe); E(f.mock.calls[0][1]?.method ?? "GET").toBe(method);
  });

  it("stream, upload, download", () => runApiFnWrappersCheck(apiOperationStream, apiOperationUpload, apiOperationDownload));
});
// AC-identity.fe-auth2.1 AC-meta.fe-http-client.1-21 AC-meta.fe-ia-nav.19
