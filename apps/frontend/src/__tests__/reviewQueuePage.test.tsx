import { beforeEach, describe, expect, it, vi } from "vitest";
import { Stage2ReviewQueue } from "@/components/reconciliation/Stage2ReviewQueue";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", async () => (await import("./helpers/statementTestFixtures")).navReconMock());
const api = vi.mocked(apiOperation), S = F.S2P, { clk, has, mkQueue, OP, s2MatchClick, see, wOp } = F;
const mQ = (o: Parameters<typeof F.mockStage2Api>[1]) => (F.mockStage2Api(api, o), F.rRev(<Stage2ReviewQueue />));

describe("Stage2ReviewQueue", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("load", async () => {
    const v1 = mQ({ queue: () => new Promise(() => {}) }); has([S.load]); v1.unmount();
    let n = 0; const v2 = mQ({ queue: () => (++n === 1 ? Promise.reject(new Error("x")) : Promise.resolve(S.q)) });
    await see(S.loadErr); clk("Retry"); await see("Pending Matches"); F.eq(n, 2); v2.unmount();
    mQ({ queue: mkQueue({ pending_matches: [] }) }); await see("No pending checks"); has(["No pending matches"]); F.hasOp(api, OP.S2_CHK, S.chkQuery);
  });

  it("409", async () => {
    const v1 = mQ({ queue: mkQueue({ consistency_checks: [S.dup], has_unresolved_checks: true }), checks: [S.dup] });
    await see(S.blockMsg); F.dis(S.appSel); await F.s2Resolve("Approve", "Looks good"); await wOp(api, OP.S2_RES, S.resReq); v1.unmount();
    mQ({ queue: S.q, extra: (op) => (op === OP.S2_BATCH ? Promise.reject(new Error(S.batchErr)) : undefined) });
    await see("Review queue"); expect(F.qRunId(api)).toBeFalsy();
    await s2MatchClick("Transfer"); clk(S.appSel); F.txtIs(await F.fAlrt(), S.batchErr);
  });

  it.each(S.batch)("%s", async (action, label, res) => {
    mQ({ queue: S.q, extra: (op) => (op === OP.S2_BATCH ? Promise.resolve(res) : undefined) });
    await s2MatchClick("Transfer"); clk(label); await wOp(api, OP.S2_BATCH, { body: { action, match_ids: ["m1"] } });
  });
});
