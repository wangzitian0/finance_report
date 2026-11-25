import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StatementReviewPage from "@/app/(main)/statements/[id]/page";
import { StatementHeader } from "@/components/statements/StatementReview";
import { ToastProvider } from "@/components/ui/Toast";
import { ANALYTICS_EVENTS, track } from "@/lib/analytics";
import { ApiError, apiOperation } from "@/lib/api";
import {
  canImportBrokerageStatement,
  statementDisplayTitle,
} from "@/lib/statusLabels";
import * as F from "./helpers/statementTestFixtures";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  searchParams: new URLSearchParams(),
}));
vi.mock("@/lib/api", async (o) => ({
  ...(await o<typeof import("@/lib/api")>()),
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(() =>
    import("./helpers/statementTestFixtures").then((m) => m.apiDlMock()),
  ),
}));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ replace: nav.replace, push: nav.push })),
  useParams: vi.fn(() => ({ id: "s1" })),
  useSearchParams: vi.fn(() => nav.searchParams),
}));
vi.mock("@/lib/analytics", async (o) => ({
  ...(await o<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
}));

const api = vi.mocked(apiOperation),
  E = expect,
  R = F.REV,
  { stmt } = R,
  mv = F.revMocks(api);
const {
  approveStmt,
  chg,
  clk,
  dis,
  dlg,
  eq,
  fBtn,
  fChg,
  fTid,
  has,
  hasC,
  hasCls,
  inDoc,
  lbl,
  mObj,
  noBtn,
  OP,
  ren,
  see,
  wCall,
  wFor,
  wValIs,
} = F;
const App = () => (
  <ToastProvider>
    <StatementReviewPage />
  </ToastProvider>
);
const renP = (
  o?: Parameters<typeof F.revPreset>[1] | Parameters<typeof F.mockStmtApi>[1],
) => {
  if (typeof o === "string") F.revPreset(api, o);
  else if (o) F.mockStmtApi(api, o);
  return ren(<App />);
};

describe("StatementReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nav.searchParams = new URLSearchParams();
  });

  it.each(F.revBlockModes)(
    "blocks %s",
    async (mode, heading, msg, acc, hideConf) => {
      renP(mode);
      await see(heading);
      has([msg]);
      if (acc) await wValIs(() => lbl(R.custLbl), acc);
      if (hideConf) noBtn(R.cfd);
      dis("Approve");
    },
  );

  it("retry, mismatch, re-parse, 3198 gap", async () => {
    const n = mv.retry(),
      v0 = renP();
    inDoc(F.role("status", R.lStmt));
    await see(R.fStmt);
    has(["network fail"]);
    clk("Retry");
    await see("statement.pdf");
    await wFor(() => eq(n(), 3));
    v0.unmount();
    const retry = vi.fn();
    mv.mismatch(retry);
    const v1 = renP();
    E(await fBtn("Approve")).toBeDisabled();
    has(R.mismatchHas);
    clk(/Re-parse statement/i);
    await wCall(retry, R.reparseBody);
    v1.unmount();
    renP("gap");
    E(await fBtn("Approve")).toBeEnabled();
    has(R.gapHas);
  });

  it("envelope confirms missing facts", async () => {
    const posted = mv.envelope(),
      { probe } = F.renProbe("statements.review.confirm-envelope", <App />, [
        "s1",
      ]);
    await see(R.confTitle);
    dis("Approve");
    await within(lbl(R.custLbl)).findByRole("option", {
      name: "DBS Cash (SGD)",
    });
    for (const [l, v] of R.confirmFields) chg(l, v);
    clk(R.cfd);
    await posted;
    await wFor(() => probe.expectDeclaredInvalidated());
    await F.wEn("Approve");
    has([R.confMsg]);
  });

  it("envelope sends the institution that the reviewer states (#3167)", async () => {
    let body: unknown = null;
    const noInstitution = {
      ...R.missing,
      institution: null,
      source_missing_facts: [
        "institution",
        "statement_currency",
        "period",
        "balances",
      ],
    };
    F.mockStmtApi(api, {
      stmt: { ...stmt, institution: null },
      rev: noInstitution,
      extra: (op, req) =>
        op === OP.ACCTS
          ? Promise.resolve(R.cashAccts)
          : op === OP.CONFIRM
            ? ((body = req?.body), Promise.resolve({ id: "review-1" }))
            : undefined,
    });
    ren(<App />);
    await see(R.confTitle);
    await see(/Institution not stated/);
    await within(lbl(R.custLbl)).findByRole("option", {
      name: "DBS Cash (SGD)",
    });
    for (const [l, v] of R.confirmFields) chg(l, v);
    dis(R.cfd);
    chg("Institution", "  Reviewed Bank ");
    clk(R.cfd);
    await wFor(() =>
      mObj(body, {
        institution: "Reviewed Bank",
        account_id: "a1",
        currency: "SGD",
      }),
    );
  });

  it("AC2477.1 / AC2826.2 account & custody", async () => {
    mv.inlineAcc();
    const v1 = renP(),
      cb = await fBtn(R.createAcc);
    await act(async () => {});
    fireEvent.click(cb);
    await see(R.dbsMsg);
    await wFor(() =>
      eq(
        (document.getElementById("custody-account") as HTMLSelectElement).value,
        "acc-1",
      ),
    );
    v1.unmount();
    const body = mv.cust2826();
    renP();
    await fChg(R.custLbl, "acc-existing");
    await approveStmt();
    await wFor(() =>
      mObj(body(), {
        account_id: "acc-existing",
        create_account_if_missing: false,
      }),
    );
  });

  it("approve, reject, prev/next, origin", () =>
    F.revNavAndOriginFlows(
      mv.nav(),
      renP,
      nav,
      track,
      ANALYTICS_EVENTS.REVIEW_APPROVED,
    ));
  it("auto-fill, 409 links, unrated", () =>
    F.revAutoFillFlows(mv, renP, ApiError));

  it("conflicts & LowConfidenceReviewModal", async () => {
    mv.conflicts();
    const { probe, unmount } = F.renProbe(
      "statements.review.resolve-conflicts",
      <App />,
      ["s1"],
    );
    E(await fBtn("Approve")).toBeDisabled();
    has([R.pauseMsg]);
    const d = await dlg(R.conflictsDlg);
    has(R.conflictTypes, d);
    probe.expectNothingInvalidated();
    clk("These rows are different transactions. Continue.", d);
    await F.wOp(api, OP.RESOLVE_CONF, { path: { statement_id: "s1" } });
    await wFor(() => probe.expectDeclaredInvalidated());
    unmount();

    mv.lowModal();
    renP();
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Review" }))[0],
    );
    await see(R.lowTitle);
    clk("Ask AI Assistant");
    hasC(nav.push, "/chat");
    clk("Salary");
    clk(/save correction/i);
    await wFor(() => F.noDlg());
    F.hasOp(api, OP.CORR, {
      body: { transaction_id: "txn-1", corrected_category: "SALARY" },
    });
  });

  it.each(R.previewCases)(
    "preview %s",
    async (original_filename, file_path, hasPrev) => {
      const s = { ...stmt, original_filename, file_path };
      renP({ stmt: s, rev: s });
      const wb = await fTid(R.wb);
      E(await within(wb).findAllByText("Salary")).not.toHaveLength(0);
      F.len(
        within(wb).queryAllByRole("heading", { name: R.pdfH }),
        hasPrev ? 1 : 0,
      );
      const col = within(wb).getByTestId(R.prevCol).closest(".order-1");
      hasCls(col, hasPrev ? "lg:col-span-7" : "lg:col-span-12");
      eq(col?.className.includes("lg:h-[600px]"), hasPrev);
    },
  );

  it("hides Import & collapses preview", async () => {
    F.revTitleOk(statementDisplayTitle, canImportBrokerageStatement);
    void StatementHeader;
    renP("bank");
    const wb = await fTid(R.wb);
    E(await within(wb).findAllByText("Salary")).not.toHaveLength(0);
    noBtn(/import brokerage/i);
    F.noTxt("pending");
    E(
      within(wb).getByRole("heading", { name: R.pdfH }).closest(".order-2"),
    ).not.toHaveClass("h-[480px]");
  });
});
