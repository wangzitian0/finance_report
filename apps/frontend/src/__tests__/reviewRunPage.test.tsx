import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuditPage from "@/app/(main)/audit/page";
import { apiOperation } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";
import { fBtn, has, mkCheck, mkMatch, mkQueue, mockStage2Api, OP } from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })), useSearchParams: vi.fn(() => new URLSearchParams("run_id=run-123")), usePathname: vi.fn(() => "/audit") }));
const mockedApi = vi.mocked(apiOperation);

describe("Run-scoped review on /audit", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("AC16.24.1/2/3 AC16.31.3 blocks approval with unresolved checks and approves clean run", async () => {
    const checks = [mkCheck({ id: "c1", check_type: "transfer_pair" }), mkCheck({ id: "c2", severity: "medium" })];
    mockStage2Api(mockedApi, {
      queue: mkQueue({ pending_matches: [mkMatch({ match_score: 90, status: "pending", amount: "10", txn_date: "2024-01-02", description: "Transfer" })], consistency_checks: checks, has_unresolved_checks: true }),
      checks,
      summary: { pending_count: 1, pending_total: "10.00", currency: "SGD", oldest_pending_date: "2024-01-01" },
    });
    const v1 = renderReviewComponent(<AuditPage /> as never);
    expect(await screen.findByRole("heading", { name: "Review this reconciliation run" })).toBeInTheDocument();
    has(["run-123", "1 unresolved transfer", "1 duplicate", "1 pending"]);
    expect(screen.getByRole("button", { name: /Approve Run/i })).toBeDisabled();
    expect(mockedApi).toHaveBeenCalledWith(OP.S2_Q, expect.objectContaining({ query: expect.objectContaining({ run_id: "run-123" }) }));
    v1.unmount();

    mockStage2Api(mockedApi, {
      queue: mkQueue({ pending_matches: [mkMatch({ id: "m1", match_score: 95, status: "pending", amount: "10" }), mkMatch({ id: "m2", match_score: 92, status: "pending", amount: "10" })] }),
    });
    renderReviewComponent(<AuditPage /> as never);
    const approveRun = await fBtn(/Approve Run/i);
    expect(approveRun).toBeEnabled();
    fireEvent.click(approveRun);
    await waitFor(() => expect(mockedApi).toHaveBeenCalledWith(OP.S2_BATCH, expect.objectContaining({ body: { action: "accept", match_ids: ["m1", "m2"], run_id: "run-123" } })));
  });
});
