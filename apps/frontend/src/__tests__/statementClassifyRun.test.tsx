import { afterEach, beforeEach, describe, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { ApiError, apiOperation } from "@/lib/api";
import type { StatementRun } from "@/lib/types";
import * as F from "./helpers/statementTestFixtures";

const showToastMock = vi.fn();
vi.mock("next/navigation", async () => (await import("./helpers/statementTestFixtures")).navS1Mock());
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", async (o) => ({ ...(await o<typeof import("@/lib/api")>()), apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), C = F.CLS, { clk, cnt, dis, mkClassifyRun, mkRun, OP, see, wCnt, wDis, wEn, wGt } = F;
const setup = (runs: () => StatementRun[], ex: Record<string, unknown> = {}, post?: () => Promise<unknown>) => { F.setupClassifyApi(api, runs, ex, post); return F.ren(<StatementDetailPage />); };

describe("Classify run", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); });
  afterEach(() => { vi.useRealTimers(); });

  it.each(["running", "requested"] as const)("blocks %s", async (st) => {
    setup(() => [mkRun({ seq: 1 }), mkClassifyRun(st)]);
    await see(C.notice); await wDis("Approve"); F.has([C.blocked]); dis(C.auto); await wGt(api, OP.REV, 0);
  });

  it("extract, confirm, poll, metadata", () => F.clsMetaPollFlow(api, setup));

  it.each(["auto-fill", "reject", "confirm"] as const)("409 %s", async (a) => {
    let runs: StatementRun[] = [mkRun({ seq: 1 })]; setup(...F.cls409Opts(a, () => runs, ApiError));
    await F.fTid(C.pa); if (a === "confirm") { await F.fChg(C.why, "Checked."); await wEn(C.cfBtn); } else await wEn("Approve");
    const rc = cnt(api, OP.RUNS), vc = cnt(api, OP.REV); runs = F.clsErrRuns(a);
    if (a === "confirm") clk(C.cfBtn); else if (a === "auto-fill") clk(C.auto); else { clk("Reject"); clk("Reject", await F.dlg("Reject Statement")); }
    await wCnt(api, a === "confirm" ? OP.CONFIRM : a === "auto-fill" ? OP.APPROVE : OP.REJECT, 1);
    await wGt(api, OP.RUNS, rc); await wGt(api, OP.REV, vc);
    if (a === "confirm") await see(C.blocked); else { await see(C.notice); await wDis("Approve"); }
  });
});
