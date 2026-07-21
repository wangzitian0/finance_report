import { afterEach, describe, expect, it, vi } from "vitest";

function response(
  body: unknown,
  init: { contentType?: string; headers?: Record<string, string>; status?: number } = {},
): Response {
  const headers = new Headers(init.headers);
  if (init.contentType) headers.set("Content-Type", init.contentType);
  return new Response(
    init.contentType === "application/json" ? JSON.stringify(body) : String(body),
    { headers, status: init.status ?? 200 },
  );
}

async function loadClient(nodeEnv: "production" | "test") {
  vi.stubEnv("NODE_ENV", nodeEnv);
  vi.resetModules();
  return import("@/lib/api-client");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("operation client runtime boundary", () => {
  it("AC-meta.public-boundary.3 materializes encoded path and repeated query values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response([], { contentType: "application/json" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { apiOperation } = await loadClient("test");

    await apiOperation(
      "list_statement_transactions_statements__statement_id__transactions_get",
      {
        path: { statement_id: "statement/one" },
        query: {
          tag: ["one", "two"],
          ignored: null,
        },
      } as never,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/statements/statement%2Fone/transactions?tag=one&tag=two",
      ),
      expect.objectContaining({ credentials: "include" }),
    );
    await expect(
      apiOperation(
        "get_account_accounts__account_id__get",
        {} as never,
      ),
    ).rejects.toThrow("Missing OpenAPI path parameter: account_id");
  });

  it("AC-meta.public-boundary.3 keeps download and multipart compatibility typed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response("snapshot", {
          headers: {
            "Content-Disposition": 'attachment; filename="snapshot.csv"',
          },
        }),
      )
      .mockResolvedValueOnce(
        response(
          { id: "statement-1", status: "pending" },
          { contentType: "application/json", status: 202 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { apiOperationDownload, apiOperationUpload } =
      await loadClient("test");
    const signal = new AbortController().signal;

    const download = await apiOperationDownload(
      "export_personal_report_package_snapshot_reports_package_snapshots__snapshot_id__export_get",
      {
        path: { snapshot_id: "snapshot/one" },
        query: { format: "csv" },
        headers: { "X-Proof": "runtime" },
        signal,
      },
    );
    const formData = new FormData();
    formData.append("file", new Blob(["statement"]), "statement.csv");
    await apiOperationUpload("upload_statement_statements_upload_post", {
      body: formData,
      headers: { "X-Proof": "runtime" },
      signal,
    });

    expect(download.filename).toBe("snapshot.csv");
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/api/reports/package/snapshots/snapshot%2Fone/export?format=csv",
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        body: formData,
        method: "POST",
        signal,
      }),
    );
  });

  it("AC-meta.public-boundary.3 delegates every transport to the production operation implementation", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/chat")) {
        return response("", { headers: { "X-Session-ID": "session-1" } });
      }
      if (url.includes("/export")) {
        return response("snapshot", {
          headers: {
            "Content-Disposition": 'attachment; filename="snapshot.json"',
          },
        });
      }
      if (url.includes("/api/statements/upload")) {
        return response(
          { id: "statement-1", status: "pending" },
          { contentType: "application/json", status: 202 },
        );
      }
      return response(
        { status: "ok", denominator: 1 },
        { contentType: "application/json" },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = await loadClient("production");

    await client.apiOperation("health_check_health_get");
    await expect(
      client.apiOperation(
        "get_account_accounts__account_id__get",
        {} as never,
      ),
    ).rejects.toThrow("Missing OpenAPI path parameter: account_id");
    const stream = await client.apiOperationStream(
      "chat_message_chat_post",
      { body: { message: "hello" } } as never,
    );
    const download = await client.apiOperationDownload(
      "export_personal_report_package_snapshot_reports_package_snapshots__snapshot_id__export_get",
      {
        path: { snapshot_id: "snapshot-1" },
        query: { format: "json" },
      },
    );
    const formData = new FormData();
    formData.append("file", new Blob(["statement"]), "statement.csv");
    await client.apiOperationUpload(
      "upload_statement_statements_upload_post",
      { body: formData } as never,
    );
    const { fetchCorrectionLoopReplay } = await import("@/lib/api");
    await fetchCorrectionLoopReplay();

    expect(stream.sessionId).toBe("session-1");
    expect(download.filename).toBe("snapshot.json");
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });
});
