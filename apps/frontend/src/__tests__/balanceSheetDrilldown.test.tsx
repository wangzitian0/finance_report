import { render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountLineageDrawer } from "@/components/reports/AccountLineageDrawer";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/packageTestFixtures";

vi.mock("@/components/ui/Overlay", async () => ({ Sheet: (await import("./helpers/packageTestFixtures")).mockSheet }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);
beforeEach(() => { api.mockReset(); });

it("AC22.3.4 AC22.3.5 drilldown + empty/error/null", async () => {
  api.mockImplementation((op: string) => Promise.resolve(op === "account_lineage_reports_account_lineage_get" ? F.BSD_LINES : F.BSD_EV) as never);
  const r1 = render(<AccountLineageDrawer target={F.BSD_TARGET} onClose={() => {}} />);
  await F.see("Salary"); await F.see("Journal line"); F.clkTxt("Salary"); await F.see("source document");
  await F.wfCall(api, "get_evidence_lineage_statements_evidence_lineage_get", expect.objectContaining({ query: expect.objectContaining({ entity_type: "journal_line" }) }));
  F.clk("Close Source lineage"); await waitFor(() => F.noTxt("source document")); r1.unmount();
  await F.assertBsdEmptyErrNull(api, AccountLineageDrawer);
}); // AC-reporting.fe-ia-reports.4 AC-reporting.fe-ia-reports.5
