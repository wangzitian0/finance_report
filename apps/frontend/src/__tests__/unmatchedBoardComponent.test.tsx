import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import UnmatchedBoard, { compatibleAccountTypes, isReviewedDispositionComplete } from "@/components/reconciliation/UnmatchedBoard";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.searchParams }));

const api = vi.mocked(apiOperation), U = F.UNM, S = F.unmSeq, P = () => <UnmatchedBoard />;
const { chg, clk, cN, dis, eq, fBtn, inDoc, lbl, noDlg, OP, ren, see, unmDlg, unmFill, valIs, wCall, wFor } = F;
const load = () => F.mockApiSeq(api, ...S.scoped.slice(0, 2));

describe("UnmatchedBoard", () => {
  beforeEach(() => { api.mockReset(); nav.searchParams = new URLSearchParams(); vi.stubGlobal("localStorage", F.memStorage()); });

  it("AC-reconciliation.first-use.1 create & post", async () => {
    nav.searchParams = new URLSearchParams("statement_id=s1"); F.mockApiSeq(api, ...S.s1);
    ren(<P />); await unmFill();
    const d = unmDlg("Create counter account", U.exp.name); valIs(within(d).getByLabelText("Type *"), "EXPENSE");
    clk(U.createAcc, d); await wFor(() => noDlg()); cN(api, 3);
    for (const [l, v] of [[U.tt, "expense"], [U.rc, "DINING"], [U.rr, "Receipt reviewed."], [U.ca, ""]]) valIs(lbl(l), v);
    dis(U.postBtn); chg(U.ca, U.exp.id); clk(U.postBtn);
    await wCall(api, OP.UNM_POST, { path: { txn_id: "u1" }, body: U.postBody });
  });

  it("Flow 13 error/incompatible & coexist", () => F.unmErrCoexistFlows(api, <P />));

  it("compatibility, completeness, flags, error", async () => {
    for (const [k, exp] of U.compat) eq(compatibleAccountTypes(k), exp);
    for (const [i, a, c, r, ok] of U.disp) eq(isReviewedDispositionComplete(i, a, c, r), ok);

    localStorage.setItem("finance-unmatched-flagged", JSON.stringify([U.item.id])); load();
    const v1 = ren(<P />); inDoc(await fBtn("Unflag local")); F.has(["Flagged locally"]);
    clk("Hide locally"); await wFor(() => F.len(screen.queryAllByText("Card payment"), 0)); v1.unmount();

    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.stubGlobal("localStorage", F.unmBadLs()); load(); const v2 = ren(<P />); fireEvent.click(await fBtn("Flag local"));
    inDoc(F.btn("Unflag local")); cN(warn, 2); warn.mockRestore(); v2.unmount();

    api.mockRejectedValueOnce(new Error(U.unavailErr)); ren(<P />); await see(U.unavailErr);
  });

  it("disposition, transfer/unknown, scoped, Decimal", () => F.unmMultiScopedFlows(api, <P />, nav));
});
