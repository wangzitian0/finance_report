import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { ApiError, apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

const showToastMock = vi.fn();
vi.mock("next/navigation", async () => (await import("./helpers/statementTestFixtures")).navS1Mock());
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", async (o) => ({ ...(await o<typeof import("@/lib/api")>()), apiOperation: vi.fn(), apiOperationDownload: vi.fn(() => (import("./helpers/statementTestFixtures")).then((m) => m.apiDlMock())) }));

const api = vi.mocked(apiOperation), R = F.RUN, P = <StatementDetailPage />, RA = "Run again";
const { alrt, callsOf, chgEl, clk, cnt, dis, eq, fAlrt, fTid, mObj, mkUserRun, OP, role, see, txtIs, wCall, wCnt, wGt, wValIs } = F;
const kw = () => role("textbox", /Keywords/), note = () => role("textbox", /Note/);
const m = (o: Parameters<typeof F.setupRunApi>[1]) => F.runMount(api, o, P);
const post = (k: string, n: string) => { chgEl(kw(), k); chgEl(note(), n); clk(RA); };

describe("Parsing attempts & Run again", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); });
  afterEach(() => { vi.useRealTimers(); });

  it("AC2994.56 attempts newest first", () => F.runVerifyAttempts(api, P));
  it("AC2994.57/63/80 hints & invalidation", () => F.runHintChecks(api, P, kw, note, post));
  it("AC2994.58/74 active, heartbeat_lost, polling", () => F.runPollCases(api, P));
  it("AC2994.60/72 limits, control chars, ZWJ", () => F.runCtrlChecks(api, P, kw, note));

  it.each(F.runErrCases(ApiError))("fixed %s", async (_l, mkErr, exp) => {
    m({ runs: () => R.s1Fail, post: () => Promise.reject(mkErr()) }); await fTid(R.panel);
    chgEl(kw(), "SECRET-KEYWORD"); clk(RA); eq((await fAlrt()).textContent, exp); F.hasC(showToastMock, exp, "error");
    eq(screen.queryAllByText(/SECRET-KEYWORD/).filter((e) => e.tagName !== "TEXTAREA"), []);
  });

  it("AC2994.61/62/81/82 reject, maxLength, approved", () =>
    F.runRejectChecks(api, P, <ConfirmDialog isOpen title="T" message="M" onConfirm={vi.fn()} onCancel={vi.fn()} />, showToastMock, ApiError));
});

describe("Classify again on statement page", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); });
  const exR = () => role("radio", "Extract again"), clR = () => role("radio", "Classify again");

  it("AC2994.134/135 extract vs classify", async () => {
    m({ status: "parsed", runs: () => [mkUserRun({ seq: 1 })] }); await fTid(R.panel);
    F.chk(exR()); F.chk(clR(), false); fireEvent.click(clR()); post("rent, salary", "Credits are salary.");
    await F.wFor(() => eq(callsOf(api, OP.RUN_POST)[0][1], R.clsReq)); await wCall(showToastMock, R.clsOk, "success"); await wValIs(kw, "");
    fireEvent.click(exR()); chgEl(kw(), "interest"); clk(RA);
    await F.wFor(() => mObj(callsOf(api, OP.RUN_POST)[1][1], R.extReq)); await wCall(showToastMock, R.parseOk, "success");
  });

  it.each(R.clsChoices)("AC2994.134 %s %s", async (status, filename, hasR, k, exp) => {
    m({ status, filename, runs: () => [] }); await fTid(R.panel);
    if (hasR) F.chk(clR()); else F.isNull(screen.queryByRole("radio"));
    if (k) chgEl(kw(), k); clk(RA); await wCnt(api, OP.RUN_POST, 1); mObj(callsOf(api, OP.RUN_POST)[0][1], exp);
  });

  it("AC2994.136 active classify & 409/422", async () => {
    const v1 = m({ status: "parsed", runs: () => R.clsRunning }); await see(R.activeTxt);
    fireEvent.click(clR()); clk(RA); await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    eq(cnt(api, OP.RUN_POST), 0); dis(RA); v1.unmount();

    let reply = F.err409(ApiError, R.errMsg.active, { active_run_id: "run-7" });
    m(F.runCls409(ApiError, () => reply)); await fTid(R.panel);
    fireEvent.click(clR()); chgEl(note(), "SECRET-NOTE-TEXT"); const b = cnt(api, OP.RUNS); clk(RA);
    txtIs(await fAlrt(), R.activeMsg); await wGt(api, OP.RUNS, b);
    reply = F.err422(ApiError, R.errMsg.unproc, { detail: [{ input: "SECRET-NOTE-TEXT" }] });
    clk(RA); await F.wFor(() => txtIs(alrt(), R.invalidMsg));
    F.isNull(screen.queryByText(/SECRET-NOTE-TEXT/, { selector: "[role=alert]" }));
  });

  it("renders collapsible debug diagnostics summary when run diagnostics exist", async () => {
    const diagRun = mkUserRun({
      seq: 1,
      diagnostics: {
        modality: "pdf_text",
        page_count: 6,
        batch_count: 1,
        pass_durations_ms: [1450],
        expected_closing: "15271.23",
        calculated_closing: "15000.00",
        balance_gap: "271.23",
        suspect_row_indices: [3, 8],
        rows_not_in_text_indices: [8],
        issue_codes: ["BALANCE_CHAIN_MISMATCH"],
        failure_code: null,
      },
    } as Partial<Parameters<typeof mkUserRun>[0]>);
    m({ runs: () => [diagRun] });
    const toggle = await screen.findByRole("button", { name: /Debug summary/i });
    fireEvent.click(toggle);
    await see(/pdf_text/i);
    await see(/271\.23/);
    await see(/3, 8/);
  });
});
