import { afterEach, expect, it, vi } from "vitest";
const res = (b: unknown, ct?: string, h?: Record<string, string>, s = 200) => {
  const hd = new Headers(h);
  if (ct) hd.set("Content-Type", ct);
  return new Response(ct ? JSON.stringify(b) : String(b), {
    headers: hd,
    status: s,
  });
};
const load = async (e: "production" | "test") => {
  vi.stubEnv("NODE_ENV", e);
  vi.resetModules();
  return import("@/lib/api");
};
const DEL = "delete_account_accounts__account_id__delete",
  EXP =
    "export_personal_report_package_snapshot_reports_package_snapshots__snapshot_id__exports_get",
  UP = "upload_statement_statements_post",
  E = expect;
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});
it("AC-meta.public-boundary.3 runtime", async () => {
  const fm1 = vi
    .fn()
    .mockResolvedValueOnce(res([], "application/json"))
    .mockResolvedValueOnce(
      res("s", undefined, {
        "Content-Disposition": 'attachment; filename="s.csv"',
      }),
    )
    .mockResolvedValueOnce(
      res({ id: "s1", status: "pending" }, "application/json", undefined, 202),
    );
  vi.stubGlobal("fetch", fm1);
  const t = await load("test"),
    sig = new AbortController().signal,
    fd = new FormData();
  fd.append("file", new Blob(["x"]), "s.csv");
  await t.apiOperation("get_journal_entry_journal_entries__entry_id__get", {
    path: { entry_id: "a/b" },
  } as never);
  E(fm1).toHaveBeenCalledWith(
    expect.stringContaining("/api/journal-entries/a%2Fb"),
    expect.objectContaining({ credentials: "include" }),
  );
  await E(t.apiOperation(DEL, {} as never)).rejects.toThrow(
    "Missing OpenAPI path parameter: account_id",
  );
  const dl1 = await t.apiOperationDownload(EXP, {
    path: { snapshot_id: "s/1" },
    query: { format: "csv" },
    headers: { "X-P": "1" },
    signal: sig,
  });
  await t.apiOperationUpload(UP, {
    body: fd,
    headers: { "X-P": "1" },
    signal: sig,
  });
  E([dl1.filename, fm1.mock.calls[1]?.[0]]).toEqual([
    "s.csv",
    expect.stringContaining(
      "/api/reports/package/snapshots/s%2F1/exports?format=csv",
    ),
  ]);
  E(fm1.mock.calls[2]?.[1]).toEqual(
    expect.objectContaining({ body: fd, method: "POST", signal: sig }),
  );
  const fm2 = vi.fn(async (u: string) =>
    u.includes("/api/chat")
      ? res("", undefined, { "X-Session-ID": "s-1" })
      : u.includes("/export")
        ? res("s", undefined, {
            "Content-Disposition": 'attachment; filename="s.json"',
          })
        : u.includes("/api/statements")
          ? res(
              { id: "s1", status: "pending" },
              "application/json",
              undefined,
              202,
            )
          : res({ status: "ok", denominator: 1 }, "application/json"),
  );
  vi.stubGlobal("fetch", fm2);
  const p = await load("production");
  await p.apiOperation("health_health_get");
  await E(p.apiOperation(DEL, {} as never)).rejects.toThrow(
    "Missing OpenAPI path parameter: account_id",
  );
  const st = await p.apiOperationStream("chat_message_chat_post", {
    body: { message: "hi" },
  } as never);
  const dl2 = await p.apiOperationDownload(EXP, {
    path: { snapshot_id: "s1" },
    query: { format: "json" },
  });
  await p.apiOperationUpload(UP, { body: fd } as never);
  await p.apiOperation(
    "get_correction_loop_replay_statements_correction_loop_replay_get",
  );
  E([st.sessionId, dl2.filename, fm2.mock.calls.length]).toEqual([
    "s-1",
    "s.json",
    5,
  ]);
});
