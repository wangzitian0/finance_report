import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LineagePanel } from "@/components/reports/AccountLineageDrawer";
import { apiOperation } from "@/lib/api";
import { has, hasOp, LIN_A, LIN_DATA, LIN_FIX, noDlg, OP, ren, see, setLin, wFor } from "./helpers/statementTestFixtures";

vi.mock("@/components/ui/Overlay", () => ({ Sheet: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: React.ReactNode }) => (isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), E = expect;
const P = (id: string | null) => <LineagePanel anchor={id ? { ...LIN_A, entity_id: id } : null} title={id ?? "n"} onClose={() => {}} />;
const hops = async () => within(await screen.findByLabelText("Lineage path")).getAllByRole("listitem");

describe("LineagePanel", () => {
  beforeEach(() => { api.mockReset(); });

  it("AC22.3.4 / AC22.7.2 chain & hops", async () => {
    setLin(api, [...LIN_FIX.flat[0]]);
    const { rerender } = ren(P(LIN_A.entity_id));
    await wFor(() => has(LIN_DATA.flat));
    hasOp(api, OP.LIN, { query: E.objectContaining({ entity_type: "journal_line" }) });

    setLin(api, [...LIN_FIX.chain[0]], [...LIN_FIX.chain[1]]);
    rerender(P("o1"));
    const items = await hops(); E(items).toHaveLength(4);
    LIN_DATA.chain.forEach((t, i) => E(items[i]).toHaveTextContent(t));
    has(LIN_DATA.s0, items[0]); has(["Version: 2"], items[1]);
  });

  it("AC22.3.5 edge graphs, blockers, error, null", async () => {
    const { rerender } = ren(P(null));
    const go = (id: string, [n, e = []]: readonly [readonly unknown[], (readonly unknown[])?], b: unknown[] = []) => { setLin(api, [...n], [...e], b); rerender(P(id)); };
    go("p1", LIN_FIX.disc); E((await hops()).at(-1)).toHaveTextContent("uploaded_document:d2");
    go("c1", LIN_FIX.cyc); await wFor(() => E(within(screen.getByLabelText("Lineage path")).getAllByRole("listitem")[0]).toHaveTextContent("source document"));
    go("m1", LIN_FIX.inc); await see("ledger line");
    go("b1", [[], []], LIN_DATA.blk); await wFor(() => has(LIN_DATA.blkTxt));
    api.mockRejectedValue(new Error("lineage boom")); rerender(P("e1")); await see("lineage boom");
    api.mockReset(); rerender(P(null)); noDlg(); E(api).not.toHaveBeenCalled();
  });
});
