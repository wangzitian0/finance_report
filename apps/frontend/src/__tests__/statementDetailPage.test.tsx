import { fireEvent } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { BrokerageImportResultBanner, StatementHeader } from "@/components/statements/StatementReview";
import { apiOperation } from "@/lib/api";
import { formatPeriod } from "@/lib/date";
import { currencyCodeOrDash as formatCode } from "@/lib/statusLabels";
import type { BankStatement } from "@/lib/types";
import * as F from "./helpers/statementTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/statementTestFixtures")).stmtsLinkMock());
const showToastMock = vi.fn();
let mockId = "s1";
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useParams: () => ({ id: mockId }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", async (o) => ({ ...(await o<typeof import("@/lib/api")>()), apiOperation: vi.fn(), apiOperationDownload: vi.fn(() => (import("./helpers/statementTestFixtures")).then((m) => m.apiDlMock())) }));

const api = vi.mocked(apiOperation), D = F.DP, dm = F.dpMocks(api), P = () => <StatementDetailPage />;
const { clk, fBtn, fClk, fTid, has, hasLnk, mkBrokRes, mkStmt, noBtn, noTxt, ren, see, tid, txt, txtIs, wCall, wFor } = F;
const H = (s: Record<string, unknown> = {}, o: Partial<ComponentProps<typeof StatementHeader>> = {}) =>
  <StatementHeader statement={mkStmt(s) as BankStatement} canImport={false} importLoading={false} onBrokerageImport={vi.fn()} formatCode={formatCode} formatPeriod={formatPeriod} {...o} />;

describe("StatementDetailPage", () => {
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); mockId = "s1"; });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("AC15 polling, abort, supersede", () => F.dpPollingChecks(api, P, showToastMock, (id) => { mockId = id; }));
  it("AC16.18 workbench & actions", () => F.dpWbChecks(api, <P />));

  it("not-found & poll stop on error", async () => {
    api.mockResolvedValueOnce(null as never); const v1 = ren(<P />); await see(D.nf); v1.unmount();
    dm.pollErr(); ren(<P />);
    await wFor(() => F.inDoc(txt(D.prog)), { timeout: 3000 });
    await wFor(() => F.inDoc(txt(/Auto-refresh Stopped/)), { timeout: 15000 });
  }, 20000);
});

describe("StatementHeader & Banner", () => {
  it("AC22.17.3 header, confidence, import", () => {
    const fn = vi.fn(), { rerender } = ren(H({}, { onBrokerageImport: fn }));
    has(D.hdrMeta); noBtn(D.impShort); noBtn("Retry Parse");
    rerender(H({ confidence_score: 70 }, { canImport: true, onBrokerageImport: fn }));
    has([D.hdr70]); clk(D.impBtn); F.cN(fn, 1);
    rerender(H({ confidence_score: null }, { canImport: true, importLoading: true, onBrokerageImport: fn }));
    noTxt(/Confidence/); F.dis(D.impShort);
  });

  it.each(D.badges)("badge %s", (status, cls) => { ren(H({ status })); F.hasCls(txt(status), cls); });

  it("BrokerageImportResultBanner skipped", () => {
    const res = mkBrokRes(), { rerender } = ren(<BrokerageImportResultBanner importResult={res} />);
    txtIs(tid(D.impBanner), D.impMsg); hasLnk(D.portLnk, "/portfolio"); noTxt("Skipped:");
    rerender(<BrokerageImportResultBanner importResult={{ ...res, skipped: 4 }} />); has(["Skipped:", "4"]);
  });
});

describe("DetailPage import & lifecycle", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.useRealTimers(); });

  it("AC17.8 import, invalidation, errors", async () => {
    dm.imp(true); const { client, unmount } = F.renQC(<P />, D.invKeys);
    await fClk(D.impBtn); txtIs(await fTid(D.impBanner), D.impMsg); hasLnk(D.portLnk, "/portfolio"); F.expectInv(client, D.invKeys); unmount();
    dm.imp(false); const v2 = ren(<P />); await fClk(D.impBtn); await fTid(D.impErrBanner); has(D.impFail); noTxt(/s3\.example\.com/); v2.unmount();
    F.mockStmtApi(api, { stmt: { ...D.brok, status: "uploaded" } }); ren(<P />); await see("moomoo-2026-01.pdf"); noBtn(D.impShort);
  });

  it("stuck refresh, retry/delete errors", () => F.dpLifecycleChecks(api, <P />, showToastMock));

  it("active accounts & LIABILITY custody", async () => {
    F.dpCcApi(api, false); const v1 = ren(<P />);
    await wCall(api, F.OP.ACCTS, { query: { is_active: true } }); await see(/Existing Card/); has([/Checking/]); v1.unmount();
    F.dpCcApi(api, true); ren(<P />); const c = await fBtn("Create account");
    await wFor(() => expect(c).toBeEnabled()); fireEvent.click(c); await wCall(api, F.OP.ACCT_POST, { body: D.ccBody });
  });
});
