import { render as R, screen as S } from "@testing-library/react";
import { beforeEach, expect as E, it, vi } from "vitest";
import { NeedsConfirmationQueue } from "@/components/audit/AuditPanels";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

beforeEach(() => api.mockReset());
it("AC22.6.1 AC22.11.3 AC22.12.4 queue, empty, retry", async () => {
  X.mockAttnOps(api, [X.ATTN_BAD_STMT], { ...X.ATTN_OK, unmatched_transactions: 5, pending_review: 3 });
  const r1 = R(<NeedsConfirmationQueue />); await X.runAttentionQueueChecks(api); r1.unmount();

  X.mockAttnOps(api, [X.makeStatement({ id: "x", original_filename: "ok.pdf", status: "approved" })]);
  const r2 = R(<NeedsConfirmationQueue />); await S.findByText("All clear"); E(S.queryAllByRole("link")).toHaveLength(0); r2.unmount();

  api.mockReset(); let n = 0;
  X.mockApiMap(api, { [X.OPS.STMT_LIST]: () => ++n === 1 ? Promise.reject(new Error("offline")) : { items: [X.ATTN_LATE_STMT], total: 1 }, [X.OPS.REC_STATS]: X.ATTN_OK, [X.OPS.REC_PEND]: { items: [], total: 0 } });
  R(<NeedsConfirmationQueue />); await X.runAttentionQueueRetry(api);
});
// AC-reconciliation.fe-ia-reconciliation.7-8 AC22.11.2
