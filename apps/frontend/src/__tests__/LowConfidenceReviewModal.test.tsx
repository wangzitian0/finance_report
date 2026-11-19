import { beforeEach, describe, it, vi } from "vitest";
import { LowConfidenceReviewModal } from "@/components/statements/StatementReview";
import { PENDING_CHAT_PROMPT_KEY } from "@/lib/chatStorage";
import * as F from "./helpers/statementTestFixtures";

const push = vi.fn(), api = vi.fn(), toast = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ apiOperation: (...a: unknown[]) => api(...a) }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: toast }) }));
vi.mock("@/lib/audit/money", async () => (await import("./helpers/statementTestFixtures")).lowMoneyMock());

const L = F.LOW, { clk, cN, has, hasC, noDlg, ren, selOpt, sub, txt, txtIs, valIs } = F;
const M = (o: Record<string, unknown> = {}) => <LowConfidenceReviewModal isOpen onClose={vi.fn()} transaction={L.txn} {...o} />;
const sel = () => F.lbl(L.cat) as HTMLSelectElement;

describe("LowConfidenceReviewModal", () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); });

  it("AC27 states & badges", () => {
    const { rerender } = ren(M({ isOpen: false })); noDlg(); rerender(M({ transaction: null })); noDlg();
    for (const [p, t] of L.states) { rerender(M(p)); has([...t]); }
    rerender(M({ transaction: L.unratedTxn }));
    const b = txt("Not rated"); F.hasCls(b, "badge", "badge-muted"); F.noCls(b, "badge-warning"); F.noTxt(/^low$/i);
  });

  it("corrections & errors", async () => {
    api.mockResolvedValueOnce({ id: "c1" }).mockRejectedValueOnce(new Error(L.dbErr));
    const onClose = vi.fn(), onSuccess = vi.fn(); ren(M({ onClose, onSuccess }));
    clk("Dining"); valIs(sel(), "DINING"); await selOpt(sel(), "TRANSPORT"); valIs(sel(), "TRANSPORT");
    clk("Dining"); clk(L.save); await F.wCall(api, F.OP.CORR, L.corrReq);
    hasC(toast, L.ok, "success"); cN(onSuccess, 1); cN(onClose, 1);
    clk(L.save); await F.wFor(() => txtIs(F.alrt(), L.dbErr)); hasC(toast, L.dbErr, "error");
    await selOpt(sel(), ""); sub(sel()); txtIs(await F.fAlrt(), L.emptyErr); cN(api, 2);
  });

  it("in-flight, Ask AI, Escape, IN chips", () => F.lowModalCloseFlow(api as never, toast, push, M, PENDING_CHAT_PROMPT_KEY));
});
