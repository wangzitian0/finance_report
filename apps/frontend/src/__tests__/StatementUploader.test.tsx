import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementUploader from "@/components/statements/StatementUploader";
import { ANALYTICS_EVENTS, track } from "@/lib/analytics";
import { apiOperationUpload } from "@/lib/api";
import { statementUploadAcceptedVector } from "./fixtures/apiVectors";
import * as F from "./helpers/statementTestFixtures";

const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperationUpload: vi.fn() }));
vi.mock("@/lib/analytics", async (o) => ({ ...(await o<typeof import("@/lib/analytics")>()), track: vi.fn() }));

const U = F.UP, up = vi.mocked(apiOperationUpload), tr = vi.mocked(track);
const { clk, cN, eq, lbl, noLbl, ren, see } = F;
const P = () => <StatementUploader />, inp = (k = "all") => F.tid(`uploader-file-${k}`);
const put = (f: File | File[], k = "all") => userEvent.upload(inp(k), f);

describe("AC3.5.3 StatementUploader", () => {
  beforeEach(() => { up.mockReset(); tr.mockReset(); showToastMock.mockReset(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("PDF uploads without a model picker or a model field", async () => {
    ren(<P />); noLbl(U.aiLbl);
    await userEvent.type(lbl(U.bankLbl), "DBS Bank"); await put(U.pdf("statement.pdf"));
    clk(/upload & parse/i); await F.wFor(() => cN(up, 1));
    const fd = up.mock.calls[0]?.[1].body as FormData; eq([fd.get("model"), fd.get("institution")], [null, "DBS Bank"]);
  });

  it("CSV, batch, drag-drop, telemetry", () =>
    F.upCsvBatchFlow((cb) => ren(<StatementUploader onUploadComplete={cb} />), up, tr, statementUploadAcceptedVector(), { start: ANALYTICS_EVENTS.UPLOAD_STARTED, ok: ANALYTICS_EVENTS.UPLOAD_SUCCEEDED }, put));

  it("upload error telemetry", () =>
    F.upErrStorageChecks(<P />, up, tr, ANALYTICS_EVENTS.UPLOAD_FAILED, put));

  it.each(U.badFiles)("kind=%s rejects %s", async (kind, name, mime, size, msg) => {
    ren(<StatementUploader kind={kind} />);
    fireEvent.change(inp(kind ?? "all"), { target: { files: [F.mkFile(name, mime, size)] } });
    await see(msg); expect(up).not.toHaveBeenCalled();
  });

  it("csv mode", async () => {
    ren(<StatementUploader kind="csv" />); noLbl(U.aiLbl);
    fireEvent.change(inp("csv"), { target: { files: [U.csv("d.csv", "x")] } }); await see("d.csv");
  });
});
