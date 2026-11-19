import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementUploader from "@/components/statements/StatementUploader";
import { fetchAiModels } from "@/lib/aiModels";
import { ANALYTICS_EVENTS, track } from "@/lib/analytics";
import { apiOperationUpload } from "@/lib/api";
import { statementUploadAcceptedVector } from "./fixtures/apiVectors";
import * as F from "./helpers/statementTestFixtures";

vi.mock("@/lib/aiModels", () => ({ fetchAiModels: vi.fn() }));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperationUpload: vi.fn() }));
vi.mock("@/lib/analytics", async (o) => ({ ...(await o<typeof import("@/lib/analytics")>()), track: vi.fn() }));

const U = F.UP, up = vi.mocked(apiOperationUpload), fetchM = vi.mocked(fetchAiModels), tr = vi.mocked(track);
const { clk, cN, eq, fLbl, lbl, noLbl, ren, see, selOpt, wValIs } = F;
const P = () => <StatementUploader />, inp = (k = "all") => F.tid(`uploader-file-${k}`);
const put = (f: File | File[], k = "all") => userEvent.upload(inp(k), f);

describe("AC3.5.3 StatementUploader", () => {
  beforeEach(() => { fetchM.mockReset().mockResolvedValue({ default_model: U.g, models: F.AI_MODELS }); up.mockReset(); tr.mockReset(); showToastMock.mockReset(); vi.stubGlobal("localStorage", F.memStorage()); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("stored/default model, persists, institution", async () => {
    localStorage.setItem(U.k, U.q); const v1 = ren(<P />); await wValIs(await fLbl(U.aiLbl), U.q);
    await userEvent.type(lbl(U.bankLbl), "DBS Bank"); await put(U.pdf("statement.pdf"));
    clk(/upload & parse/i); await F.wFor(() => cN(up, 1));
    const fd = up.mock.calls[0]?.[1].body as FormData; eq([fd.get("model"), fd.get("institution")], [U.q, "DBS Bank"]); v1.unmount();

    localStorage.clear(); ren(<P />); const s2 = await fLbl(U.aiLbl); await wValIs(s2, U.g);
    await selOpt(s2, U.q); eq(localStorage.getItem(U.k), U.q);
  });

  it("CSV, batch, drag-drop, telemetry", () =>
    F.upCsvBatchFlow((cb) => ren(<StatementUploader onUploadComplete={cb} />), up, tr, statementUploadAcceptedVector(), { start: ANALYTICS_EVENTS.UPLOAD_STARTED, ok: ANALYTICS_EVENTS.UPLOAD_SUCCEEDED }, put));

  it("missing default, fetch/upload & storage errors", () =>
    F.upErrStorageChecks(<P />, fetchM, up, tr, ANALYTICS_EVENTS.UPLOAD_FAILED, put));

  it.each(U.badFiles)("kind=%s rejects %s", async (kind, name, mime, size, msg) => {
    ren(<StatementUploader kind={kind} />);
    fireEvent.change(inp(kind ?? "all"), { target: { files: [F.mkFile(name, mime, size)] } });
    await see(msg); expect(up).not.toHaveBeenCalled();
  });

  it("csv mode", async () => {
    fetchM.mockClear(); ren(<StatementUploader kind="csv" />); noLbl(U.aiLbl); expect(fetchM).not.toHaveBeenCalled();
    fireEvent.change(inp("csv"), { target: { files: [U.csv("d.csv", "x")] } }); await see("d.csv");
  });
});
