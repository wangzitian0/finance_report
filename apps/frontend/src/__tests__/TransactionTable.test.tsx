import { within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TransactionTable } from "@/components/statements/StatementReview";
import * as money from "@/lib/audit/money";
import { normalizeBankStatement, toTransactionViewModel } from "@/lib/types";
import * as F from "./helpers/statementTestFixtures";

const E = expect, X = F.TXN, { allTxt, clk, has, hasCls, inDoc, noRole, ren, tid } = F, reg = () => tid(X.desk);
const T = (txns: unknown, o: Record<string, unknown> = {}) => <TransactionTable transactions={txns as never} currency="SGD" {...o} />;

describe("TransactionTable", () => {
  const origMM = window.matchMedia;
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: origMM }); });

  it("layout, responsive margin, callbacks", () => {
    const onSel = vi.fn(), { rerender } = ren(T(X.sample));
    has(["Transactions"]); F.gt(allTxt("Coffee").length, 0);
    for (const r of X.noRoles) noRole("button", r); noRole("textbox"); noRole("combobox");
    const r = reg(), tbl = r.querySelector("table");
    hasCls(r, ...X.cls); F.noCls(r, "overflow-hidden"); hasCls(tbl, ...X.tblCls);
    E(tbl).toHaveStyle(X.tbl4); E(within(r).getByText(/-SGD/)).toBeTruthy();

    Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: undefined });
    rerender(T(X.sample, { onSelectTransaction: onSel }));
    E(tbl).toHaveStyle(X.tbl16); inDoc(tid(X.mob1));
    has(["Action"]); clk("Review"); E(onSel).toHaveBeenCalledWith(X.sample[0]); clk("Review / Fix"); F.cN(onSel, 2);
  });

  it("confidence, nullish, currency", () => {
    const spy = vi.spyOn(money, "formatCurrencyLocale");
    ren(T(X.tiers)); const w = within(reg());
    for (const [t, c] of X.badges) E(w.getByText(t).className).toContain(c);
    F.gt(w.getAllByText("HIGH").length, 0);
    E(spy.mock.calls.map((c) => c[0])).toEqual(E.arrayContaining(["3.50", "50"])); spy.mockRestore();
    ren(T(undefined)); has(["0 total"]);
  });

  it("AC2465.2 & AC23/27 order, status, unrated", () =>
    F.txnOrderFlow(T, normalizeBankStatement as never, toTransactionViewModel as never));
});
