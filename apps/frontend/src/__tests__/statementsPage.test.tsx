import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementsPage from "@/app/(main)/upload/page";
import { apiOperation } from "@/lib/api";
import type { BankStatement } from "@/lib/types";
import * as F from "./helpers/statementTestFixtures";

const showToastMock = vi.fn(), routerPushMock = vi.fn();
vi.mock("next/link", async () => (await import("./helpers/statementTestFixtures")).stmtsLinkMock());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: routerPushMock }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/components/statements/StatementUploader", async () => (await import("./helpers/statementTestFixtures")).stmtsUploaderMock());
vi.mock("@/components/pricing/GuidedEvidenceForm", () => ({ default: () => <div data-testid="manual-evidence-form" /> }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/components/ui/ConfirmDialog", async () => (await import("./helpers/statementTestFixtures")).stmtsConfirmMock());
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

const api = vi.mocked(apiOperation), M = F.STMTS, P = () => <StatementsPage />;
const { allTxt, clk, eq, fRole, fTid, has, hasC, hasLnk, inDoc, isNull, len, noTxt, ren, see, tid, txt, txtIs, wFor } = F;
const stmt = (id: string, name: string, status: BankStatement["status"], ex: Record<string, unknown> = {}) => F.mkStmt({ id, original_filename: name, status, opening_balance: 100, closing_balance: 200, ...ex });
const ps = F.stmtsPresets(api, stmt);

describe("StatementsPage", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); routerPushMock.mockClear(); F.stmtsMockState.onUpload = null; });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("AC16 polling & abort", () => F.stmtsPollFlow(api, <P />, stmt));

  it("intakes & upload history", async () => {
    ps.retry(); const { container } = ren(<P />);
    await wFor(() => len(allTxt("load failed"), 2)); clk("Retry loading statements");
    await wFor(() => has(M.intakes)); inDoc(tid("manual-evidence-form")); hasLnk(/Back to Audit/i, "/audit");
    const folded = container.querySelectorAll("details"); len(folded, 2); folded.forEach((n) => eq(n.hasAttribute("open"), false));
    eq([screen.queryByTestId("source-intake-bank_statement"), screen.queryByTestId("source-intake-manual_record")], [null, null]);
    fireEvent.click(txt(M.upBtn)); await see("stmt.pdf");
  });

  it.each(M.statuses)("status %s", async (status, file, label, forbidden, clickRev) => {
    F.mockStmtsPageApi(api, { statements: [{ items: [stmt("s9", file, status)] }] });
    ren(<P />); await see(file); has([label]); if (forbidden) noTxt(forbidden);
    if (clickRev) { clk(/Review/i); hasC(routerPushMock, "/statements/s9"); }
  });

  it("polling & delete lifecycle", () => F.stmtsDelFlow(api, <P />, showToastMock, ps));

  it("brokerage import retry & reason", async () => {
    F.stmtsBrokApi(api); const { client, unmount } = F.renQC(<P />, M.keys), r1 = await fTid(M.ibkrRow);
    has(["Import failed", M.brokFailMsg, "No statement period", "Not checked"], r1); noTxt("Economic review required: intent_missing", r1);
    for (const f of [/Parsing/, /Ready to review/, /Review & Approve/]) noTxt(f, r1);
    clk("Retry import", r1); await wFor(() => inDoc(within(tid(M.ibkrRow)).getByText(M.ready)));
    hasC(showToastMock, M.impOk, "success"); F.expectInv(client, M.keys); unmount();

    ps.moomoo(); ren(<P />); has(["Import failed", M.moomooReason], await fTid("upload-statement-row-s-moomoo"));
  });

  it("links, titles, notices, transfers, coverage", async () => {
    ps.wf(); ren(<P />); await see("parsed.pdf");
    for (const b of F.stmtsActionBtns) clk(b);
    for (const r of F.stmtsActionRoutes) hasC(routerPushMock, r);
    txtIs(tid("upload-processing-summary"), "1 parsing · 1 parsed · 1 approved");
    hasLnk("DBS (2026-02-01 – 2026-02-28)", "/statements/s-fallback");
    F.hasAttr(screen.getAllByRole("link", { name: "Open March statement needs review" })[0], "href", "/statements/s1");
    txtIs(await fRole("region", "Transfers in flight"), "10d");
    const cov = await fRole("region", "Statement coverage"); for (const t of M.covTexts) txtIs(cov, t);
    isNull(document.querySelector(M.noLinks));
  });
});
