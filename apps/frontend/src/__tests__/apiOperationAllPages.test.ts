import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetRedirectGuard } from "@/lib/api";
import { MAX_PAGES, MAX_PAGE_LIMIT, apiOperationAllPages } from "@/lib/apiPages";

type Parameter = { name: string; in: string; schema?: { maximum?: number } };
const openapi = JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../openapi.json"), "utf-8")) as {
  paths: Record<string, Record<string, { parameters?: Parameter[] }>>;
};

function pagedFetch(rows: number, withTotal: boolean) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    const limit = Number(url.searchParams.get("limit"));
    const offset = Number(url.searchParams.get("offset"));
    const items = Array.from({ length: Math.max(0, Math.min(limit, rows - offset)) }, (_, i) => ({ n: offset + i }));
    const body = withTotal ? { items, total: rows } : { items };
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => null } };
  });
}

describe("apiOperationAllPages (#3156)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); resetRedirectGuard(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads every page of a list with a total", async () => {
    const rows = MAX_PAGE_LIMIT * 2 + 7;
    const fetchMock = pagedFetch(rows, true);
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiOperationAllPages("list_statements_statements_get");
    expect(result.items).toHaveLength(rows);
    expect(result.total).toBe(rows);
    expect(result.items.map((item) => (item as unknown as { n: number }).n)).toEqual(Array.from({ length: rows }, (_, i) => i));
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("stops at the total when the last page is full, and keeps the caller's query", async () => {
    const fetchMock = pagedFetch(MAX_PAGE_LIMIT * 2, true);
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiOperationAllPages("list_statement_runs_statements__statement_id__runs_get", { path: { statement_id: "s1" } });
    expect(result.items).toHaveLength(MAX_PAGE_LIMIT * 2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const urls = fetchMock.mock.calls.map(([input]) => new URL(String(input), "http://localhost"));
    expect(urls.map((url) => url.pathname)).toEqual(["/api/statements/s1/runs", "/api/statements/s1/runs"]);
    expect(urls.map((url) => url.searchParams.get("offset"))).toEqual(["0", String(MAX_PAGE_LIMIT)]);
  });

  it("raises after MAX_PAGES full pages when the server ignores offset", async () => {
    const fullPage = { items: Array.from({ length: MAX_PAGE_LIMIT }, (_, i) => ({ n: i })) };
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => fullPage, text: async () => JSON.stringify(fullPage), headers: { get: () => null } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiOperationAllPages("get_journal_entry_audit_journal_entries__entry_id__audit_get", { path: { entry_id: "e1" } })).rejects.toThrow(/more than 200 full pages/);
    expect(fetchMock).toHaveBeenCalledTimes(MAX_PAGES);
  });

  it("stops at the first short page of a list without a total", async () => {
    const fetchMock = pagedFetch(MAX_PAGE_LIMIT + 1, false);
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiOperationAllPages("get_journal_entry_audit_journal_entries__entry_id__audit_get", { path: { entry_id: "e1" } });
    expect(result.items).toHaveLength(MAX_PAGE_LIMIT + 1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("MAX_PAGE_LIMIT equals the limit maximum in openapi.json of each list that the screens read in full", () => {
    const paths = ["/statements", "/statements/pending-review", "/statements/{statement_id}/runs", "/reconciliation/transfers/pending", "/journal-entries/{entry_id}/audit"];
    const maxima = paths.map((path) => openapi.paths[path].get.parameters?.find((p) => p.in === "query" && p.name === "limit")?.schema?.maximum);
    expect(maxima).toEqual(paths.map(() => MAX_PAGE_LIMIT));
  });
});
