import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConsistencyChecksPanel, PendingMatchesPanel, ResolveCheckDialog, RunSummaryPanel, Stage2Filters, Stage2ReviewQueue } from "@/components/reconciliation/Stage2ReviewQueue";
import { apiOperation } from "@/lib/api";
import { checkSeverityColor, checkTypeLabel } from "@/lib/statusLabels";
import * as F from "./helpers/statementTestFixtures";

const runIdState = vi.hoisted(() => ({ current: null as string | null }));
const nav = vi.hoisted(() => ({ pathname: "/reconciliation", replace: vi.fn(), push: vi.fn(), searchParams: new URLSearchParams() }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace, push: nav.push }), useSearchParams: () => nav.searchParams, usePathname: () => nav.pathname }));

const api = vi.mocked(apiOperation), S = F.S2, { chgEl, clk, dlg, en, esc, fBtn, fClk, fTid, has, hasAttr, hasCls, mkQueue, noDlg, OP, s2MatchClick, see, tid, wCall, wFor } = F;
const origMM = window.matchMedia, rQ = (o: Parameters<typeof F.mockStage2Api>[1], id: string | null = null, sp = "") => { runIdState.current = id; nav.searchParams = new URLSearchParams(sp); F.mockStage2Api(api, o); return F.rRev(<Stage2ReviewQueue runId={runIdState.current} />); };

describe("AC8.13.48 Stage2ReviewQueue", () => {
  beforeEach(() => { api.mockReset(); nav.pathname = "/reconciliation"; runIdState.current = null; nav.searchParams = new URLSearchParams(); nav.replace.mockReset(); nav.push.mockReset(); });
  afterEach(() => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: origMM }); });

  it("mobile, run gate, URL, desktop", async () => {
    F.mockMM(); const v1 = rQ({ queue: mkQueue({ pending_matches: [S.pm] }) }), card = await fTid(S.card); has([S.sal], card);
    fireEvent.click(within(card).getByRole("checkbox", { name: S.sel1 })); await wFor(() => has(["1 selected"]));
    en("Reject"); en(S.approveSel); v1.unmount();

    const v2 = rQ({ queue: mkQueue({ pending_matches: [S.pm] }) }, "mobile-run");
    await see("Run approval gate"); en(S.approveRun); await fTid(S.card); v2.unmount();

    const v3 = rQ({ queue: mkQueue({ pending_matches: [] }) }, null, "tab=review-queue&from=attention&min_score=0");
    await wCall(nav.replace, S.u1, { scroll: false }); v3.unmount();

    Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: undefined });
    rQ({ queue: mkQueue({ pending_matches: [S.pm] }) }); await see("Pending Matches"); F.inDoc(tid(S.card));
    const reg = tid(S.desk), tbl = reg.querySelector("table");
    hasCls(reg, "overflow-hidden"); hasCls(tbl, ...S.tblClass); expect(tbl).toHaveStyle({ width: "calc(100% - 4px)" });
  });

  it("filters, errors, client filter", async () => {
    const v1 = rQ(F.s2ErrApis.batchOk, "run 1", S.q1); await see("Review queue"); has(["run 1"]); clk("HIGH");
    const [ct, st] = screen.getAllByRole("combobox"); chgEl(ct, "anomaly"); chgEl(st, "resolved");
    clk("Select all"); await wFor(() => has(["1 selected"])); clk("Deselect all"); await wFor(() => has(["0 selected"]));
    clk(S.approveRun); await wCall(nav.replace, S.u2, { scroll: false }); v1.unmount();

    const v2 = rQ(F.s2ErrApis.resErr); await see("manual_review");
    clk("Resolve"); await dlg(S.dlg); esc(); await wFor(() => noDlg(S.dlg));
    clk("Resolve"); fireEvent.click(document.querySelector(S.overlay) as HTMLElement); await wFor(() => noDlg(S.dlg));
    const d = await F.s2Resolve("Reject", "Keep reviewing");
    await wCall(api, OP.S2_RES, expect.objectContaining({ path: { check_id: "c2" }, body: { action: "reject", note: "Keep reviewing" } }));
    await F.wEn("Cancel", d); clk("Cancel", d); v2.unmount();

    const v3 = rQ(F.s2ErrApis.batchErr, "run-2");
    await see("Review queue"); clk("Select all"); clk(S.approveSel); await see("approve run failed");
    clk("Reject"); await see("batch reject failed"); await fClk(S.approveRun); await wFor(() => F.gte(F.cnt(api, OP.S2_BATCH), 3)); v3.unmount();

    rQ(F.s2ErrApis.sumErr, "run-3"); await see("manual_review"); clk("HIGH"); await F.wNoTxt("manual_review"); F.gt(F.allTxt("Duplicate").length, 0);
    await s2MatchClick(S.sal); await wFor(() => has(["1 selected"]));
    await s2MatchClick(S.sal); await wFor(() => has(["0 selected"]));
  });

  it.each(S.guards)("run guard: %s", async (title, q, summary, checks) => {
    rQ({ queue: q, summary, checks }, "run-4");
    const b = await fBtn(S.approveRun); expect(b).toBeDisabled(); hasAttr(b, "title", title);
  });
});

describe("Stage2 extracted parts", () => {
  it("AC22.17.2 panels, filters, summary, dialog, labels", () =>
    F.s2CheckParts({ PendingMatchesPanel, ConsistencyChecksPanel, Stage2Filters, RunSummaryPanel, ResolveCheckDialog, checkSeverityColor, checkTypeLabel } as never));
});
