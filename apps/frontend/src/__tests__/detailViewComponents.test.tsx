import { describe, expect, it, vi } from "vitest";
import { AccountDetailsSidebar } from "@/components/accounts/AccountFormModal";
import JournalEntryDetailsModal from "@/components/journal/JournalEntryDetailsModal";
import { apiOperation } from "@/lib/api";
import { allTxt, DETAIL_ACC, DETAIL_DATA, DETAIL_JE, has, lnP, mkEntry, ren, see, tid, txt, wFor } from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), E = expect;
const S = (a: unknown, isOpen = true) => <AccountDetailsSidebar account={a as never} isOpen={isOpen} onClose={vi.fn()} />;
const M = (e: unknown, isOpen = true) => <JournalEntryDetailsModal entry={e as never} isOpen={isOpen} onClose={vi.fn()} />;
const mob = (id: string) => tid(`journal-line-mobile-${id}`, tid("journal-lines-mobile"));
const mockRes = (items: unknown[]) => api.mockResolvedValueOnce({ items, total: items.length } as never);

describe("Detail view components", () => {
  it("AccountDetailsSidebar", async () => {
    const { container, rerender } = ren(S(null, false)); E(container.firstChild).toBeNull();
    mockRes([]); rerender(S(DETAIL_ACC.cash)); has(["Cash", "ASSET", "SGD", /Current Balance/i]); await see("No recent transactions found");
    mockRes([]); rerender(S(DETAIL_ACC.bank)); await wFor(() => has(["Bank", "1001", "Main account"]));
    mockRes([DETAIL_JE.acc]); rerender(S(DETAIL_ACC.wallet)); await wFor(() => has(["Pay", "DEBIT"]));
  });

  it("AC16.25.3 / AC-ledger.12.1 JournalEntryDetailsModal", () => {
    const { container, rerender } = ren(M(null, false)); E(container.firstChild).toBeNull();
    rerender(M(DETAIL_JE.base)); has(DETAIL_DATA.baseTexts);
    for (const t of ["a1", "DEBIT", "a2", "CREDIT"]) E(allTxt(t).length).toBeGreaterThan(0);
    rerender(M(DETAIL_JE.mob)); has(DETAIL_DATA.mobChecks, mob("ld"));
    E(allTxt(/1,234\.56/, mob("ld"))).toHaveLength(2); has(["income:salary:mobile"], mob("lc"));
    rerender(M(DETAIL_JE.fx)); has(["1.350000", /135\.00/], mob("lu")); has(["1.000000", /^SGD\s*0\.00$/], mob("lm"));
  });

  it.each(DETAIL_DATA.statuses)("status %s", (status) => {
    ren(M(mkEntry({ id: `s-${status}`, entry_date: "2023-03-03", memo: "m", source_type: "import_file", status, lines: [lnP("l3", "a3", "DEBIT", "10")] })));
    E(txt(status)).toBeInTheDocument();
  });
});
