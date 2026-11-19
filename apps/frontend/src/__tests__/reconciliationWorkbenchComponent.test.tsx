import { within } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import ReconciliationWorkbench from "@/components/reconciliation/Workbench";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/components/reconciliation/UnmatchedBoard", async () => (await import("./helpers/statementTestFixtures")).wbStubMocks.unm());
vi.mock("@/components/reconciliation/Stage2ReviewQueue", async () => (await import("./helpers/statementTestFixtures")).wbStubMocks.s2());
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.searchParams, useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/reconciliation" }));

const api = vi.mocked(apiOperation), W = F.WB, P = () => <ReconciliationWorkbench />;
const { clk, eq, gt, gte, has, hasAttr, inDoc, len, ren, see, txtIs, wCall, wFor } = F;
const nLinks = () => within(F.role("navigation", W.navLbl)).getAllByRole("link");
const wb = (ov?: Parameters<typeof F.mockWbApi>[1]) => F.mockWbApi(api, ov);

describe("ReconciliationWorkbench", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); nav.searchParams = new URLSearchParams("tab=matches"); });

  it("AC16.20.1/2/6 stats, anomalies, actions", async () => {
    wb(F.wbPresets.anom); const v1 = ren(<P />);
    gt((await F.fAllTxt("Transfer")).length, 0); has(W.hdr); await see(W.anomTitle);
    const h = Array.from(document.querySelectorAll("[style]")).map((el) => (el as HTMLElement).style.height);
    gte(h.filter((x) => x === "0%").length, 2); gte(h.filter((x) => x.endsWith("%") && x !== "0%").length, 2); v1.unmount();

    wb(); ren(<P />); await see("Rent");
    for (const [b, op, payload] of W.actions) { clk(b); await wCall(api, op, payload); }
  });

  it("AC8_13_48 failures, refresh, links", () => F.wbErrRefreshLinksFlows(api, <P />));

  it.each(W.inv)("AC-testing.fe-async.2 %s", async (flow, btnName, op, payload) => {
    wb(); const { probe } = F.renProbe(flow, <P />);
    await see("Rent"); probe.expectNothingInvalidated(); clk(btnName);
    await wCall(api, op, payload); await wFor(() => probe.expectDeclaredInvalidated());
  });

  it.each(W.tabs)("AC-reconciliation.fe-tabs.1 %s", (query, activeTab, content) => {
    wb(); nav.searchParams = new URLSearchParams(query); ren(<P />); const ls = nLinks();
    eq(ls.map((l) => l.getAttribute("href")), W.hrefs);
    const cur = ls.filter((l) => l.getAttribute("aria-current") === "page");
    len(cur, 1); txtIs(cur[0], activeTab); has([content]);
    if (query.includes("run_id=run-42")) hasAttr(F.tid("mock-review-queue"), "data-run-id", "run-42");
  });

  it.each(W.defs)("AC-reconciliation.fe-tabs.2 %s (%i)", async (query, unm, activeTab, content) => {
    const w = F.wbPresets.waitStat(); wb(w.ov); nav.searchParams = new URLSearchParams(query); ren(<P />);
    len(nLinks().filter((l) => l.getAttribute("aria-current") === "page"), 0);
    inDoc(F.role("status", "Loading reconciliation"));
    w.resolve({ ...W.stats, unmatched_transactions: unm, matched_transactions: 5 - unm, pending_review: 0 });
    await see(content); const cur = nLinks().filter((l) => l.getAttribute("aria-current") === "page");
    len(cur, 1); txtIs(cur[0], activeTab);
  });
});
