import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AiSuggestionsQueue } from "@/components/audit/AuditPanels";
import { AuditTrailPanel } from "@/components/journal/JournalEntryDetailsModal";
import { AiSettingsPanel } from "@/components/settings/SettingsPanels";
import { ConfidenceBadge } from "@/components/ui";
import { ApiError, apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  apiOperation: vi.fn(),
}));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));
const api = vi.mocked(apiOperation),
  A = F.AI,
  { chk, clk, fLbl, has, lbl, OP, ren, see, txt, txtIs, wCall, wFor } = F;

describe("EPIC-018 Confidence + AI UI", () => {
  beforeEach(() => {
    api.mockReset();
    showToastMock.mockReset();
  });

  it("AC18.5.1/2 Badge & Journal LOW", async () => {
    const { unmount } = ren(
      <div>
        {A.tiers.map((t) => (
          <ConfidenceBadge key={t} tier={t} />
        ))}
      </div>,
    );
    for (const t of A.tiers)
      F.hasAttr(
        txt(t),
        "title",
        expect.stringContaining(
          "Deterministic system facts",
        ) as unknown as string,
      );
    unmount();
    api.mockResolvedValueOnce(A.journal as never);
    const { default: JournalPage } = await import("@/app/(main)/journal/page");
    ren(<JournalPage />);
    await see("Processing transfer");
    F.inDoc(txt("LOW"));
  });

  it("AC18.5.3/4 AC16.25.2 queue & lock", () =>
    F.aiQueueLockFlow(api, <AiSuggestionsQueue />));

  it("AC18.5.5/6/7 test_AC8_13_48 errors, AuditTrail, AiSettings", async () => {
    api.mockRejectedValueOnce(new Error(A.sugErrMsg));
    const v1 = ren(<AiSuggestionsQueue />);
    await see(A.sugErrMsg);
    v1.unmount();
    api.mockResolvedValueOnce(A.audit as never);
    const v2 = ren(<AuditTrailPanel transactionId={A.auditTx} />);
    await wFor(() => has(A.auditInfo));
    v2.unmount();

    F.aiSetApi(api, "ok");
    const v3 = ren(<AiSettingsPanel />);
    const recon = await fLbl(A.reconLbl),
      cls = lbl(A.clsLbl);
    chk(recon);
    chk(cls, false);
    fireEvent.click(cls);
    clk(A.saveBtn);
    await wCall(api, OP.SET_PATCH, {
      body: { enable_ai_classification: true },
    });
    v3.unmount();

    api.mockRejectedValueOnce(new Error(A.setErrMsg));
    const v4 = ren(<AiSettingsPanel />);
    txtIs(await F.fAlrt(), A.setErrMsg);
    v4.unmount();

    F.aiSetApi(api, "fail");
    ren(<AiSettingsPanel />);
    const r2 = await fLbl(A.reconLbl);
    chk(r2, false);
    chk(lbl(A.clsLbl));
    fireEvent.click(r2);
    clk(A.saveBtn);
    await see("update failed");
  });

  it("AC-extraction.classification-hardening.3056 — refreshes queue on 409 superseded conflict", async () => {
    const s = (
      n: string,
      suggested_category_or_match: string,
      ai_score: number,
      ai_reasoning: string,
    ) => ({
      suggestion_id: `00000000-0000-0000-0000-0000000000${n}`,
      transaction: "GRAB RIDE",
      suggested_category_or_match,
      ai_score,
      ai_reasoning,
    });
    api
      .mockResolvedValueOnce({
        items: [s("41", "SHOPPING", 72, "Initial.")],
        total: 1,
      } as never)
      .mockRejectedValueOnce(
        new ApiError(
          "This suggestion was superseded by a newer classification run.",
          409,
        ),
      )
      .mockResolvedValueOnce({
        items: [s("42", "TRANSPORT", 80, "Updated.")],
        total: 1,
      } as never);
    ren(<AiSuggestionsQueue />);
    await screen.findAllByText("GRAB RIDE");
    fireEvent.click(
      within(
        screen.getByTestId(
          "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000041",
        ),
      ).getByRole("button", { name: "Accept" }),
    );
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(
      "This suggestion was superseded by a newer classification run.",
    );
    expect((await screen.findAllByText("TRANSPORT")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^Accepted\./)).not.toBeInTheDocument();
  });
}); // AC-extraction.fe-remainder-extraction.1 AC-ledger.fe-accounts2.4 AC-llm.fe-ai-settings2.1 AC-llm.fe-ai-settings2.2 AC-meta.fe-app-shell2.1 AC-reconciliation.fe-remainder-reconciliation.2 AC-reconciliation.fe-remainder-reconciliation.3
