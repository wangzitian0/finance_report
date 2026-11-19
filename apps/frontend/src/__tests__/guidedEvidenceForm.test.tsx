import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GuidedEvidenceForm, { SOURCE_CLASS_CONFIGS, VALUATION_BASIS_OPTIONS, validateEvidenceForm } from "@/components/pricing/GuidedEvidenceForm";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), E = expect, V = F.EV, origMM = window.matchMedia;
const G = (o: Record<string, unknown> = {}) => <GuidedEvidenceForm {...o} />;
const { chg, clk, eq, evFill, OP, ren, see, wCall } = F;
const mv = (l = { items: [], total: 0 } as Parameters<typeof F.mockValApi>[1], p?: Promise<unknown>) => F.mockValApi(api, l, p);

describe("GuidedEvidenceForm", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); });
  afterEach(() => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: origMM }); });

  it("AC11.9.6 validation", () => {
    E(validateEvidenceForm(V.empty).blockers).toEqual(E.arrayContaining(V.blockers));
    for (const v of V.bad) { const r = validateEvidenceForm({ ...V.base, value: v }); E(r.errors.value).toBeTruthy(); E(r.blockers).toContain("missing_value"); }
    for (const v of V.good) E(validateEvidenceForm({ ...V.base, value: v }).blockers).not.toContain("missing_value");
    eq(validateEvidenceForm({ ...V.base, source_class: "liability_statement", valuation_basis: "bank_statement" }), V.okRes);
  });

  it.each(V.miss)("missing %s", async (l, err) => {
    mv(); ren(G()); evFill(); chg(l, ""); clk(V.save); await see(err);
    if (l === "Valuation basis") F.inDoc(F.tid(V.blk));
    eq(F.cnt(api, OP.VAL_POST), 0);
  });

  it("AC11.9.4/7 submit, invalidate, error", async () => {
    mv(); const { probe, unmount } = F.renProbe("assets.guided-evidence-create", G({ initialSourceClass: "esop_rsu_plan" }));
    evFill(); chg(V.anc, "grant-2026.pdf p3"); probe.expectNothingInvalidated(); clk(V.save);
    await wCall(api, OP.VAL_POST, { body: E.objectContaining(V.p1) });
    await wCall(showToastMock, "Evidence saved", "success"); await F.wFor(() => probe.expectDeclaredInvalidated()); unmount();

    mv(); const v2 = ren(G()); for (const [l, val] of F.evCls2Fields) chg(l, val);
    evFill(); clk(V.save); await wCall(api, OP.VAL_POST, { body: E.objectContaining(V.p2) }); v2.unmount();

    mv({ items: [], total: 0 }, Promise.reject(new Error("save failed"))); ren(G());
    evFill(); clk(V.save); await wCall(showToastMock, V.saveErr, "error");
  });

  it("AC11.9.8/9 manual-trusted, mobile, unknown", () =>
    F.evPanelMobileFlow(api, mv, G, SOURCE_CLASS_CONFIGS, VALUATION_BASIS_OPTIONS));
});
