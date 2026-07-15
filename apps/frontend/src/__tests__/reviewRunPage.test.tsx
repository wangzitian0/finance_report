import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import RunReviewPage from "@/app/(main)/review/run/[runId]/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
    usePathname: vi.fn(() => "/review/run/run-123"),
}));

const mockedApi = vi.mocked(apiFetch);

describe("RunReviewPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    // AC-reconciliation.fe-stage2-review.20 / AC-reconciliation.fe-stage2-review.21 / AC-reconciliation.fe-stage2-review.24
    it("AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval", async () => {
        const checks = [
            {
                id: "c-transfer",
                check_type: "transfer_pair",
                status: "pending",
                related_txn_ids: [],
                details: { message: "Unpaired transfer out" },
                severity: "high",
                resolved_at: null,
                resolution_note: null,
                created_at: "2024-01-01",
                updated_at: "2024-01-01",
            },
            {
                id: "c-duplicate",
                check_type: "duplicate",
                status: "pending",
                related_txn_ids: [],
                details: { message: "Duplicate card charge" },
                severity: "medium",
                resolved_at: null,
                resolution_note: null,
                created_at: "2024-01-01",
                updated_at: "2024-01-01",
            },
        ];

        mockedApi.mockImplementation((path: string) => {
            if (path.includes("/stage2/queue")) {
                expect(path).toContain("run_id=run-123");
                return Promise.resolve({
                    pending_matches: [{ id: "m1", match_score: "90", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Transfer" }],
                    consistency_checks: checks,
                    has_unresolved_checks: true,
                } as any);
            }
            if (path.includes("consistency-checks/list")) {
                return Promise.resolve({ items: checks } as any);
            }
            if (path.includes("/accounts/processing/summary")) {
                return Promise.resolve({ pending_count: 1, pending_total: "10.00", currency: "SGD", oldest_pending_date: "2024-01-01" } as any);
            }
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<RunReviewPage /> as any);

        expect(await screen.findByText("Review queue")).toBeInTheDocument();
        expect(
            screen.getByText("Matches and checks from this reconciliation run that need a human check before they post."),
        ).toBeInTheDocument();
        expect(screen.getByText("run-123")).toBeInTheDocument();
        expect(screen.getByText("1 unresolved transfer")).toBeInTheDocument();
        expect(screen.getByText("1 duplicate")).toBeInTheDocument();
        expect(screen.getByText("1 pending")).toBeInTheDocument();

        const approveRun = screen.getByRole("button", { name: /Approve Run/i });
        expect(approveRun).toBeDisabled();
    });

    // AC-reconciliation.fe-stage2-review.22
    it("AC16.24.3 approves all pending matches through the batch approval API", async () => {
        const data = {
            pending_matches: [
                { id: "m1", match_score: "95", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Bank A out" },
                { id: "m2", match_score: "92", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Bank B in" },
            ],
            consistency_checks: [],
            has_unresolved_checks: false,
        };

        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path.includes("/stage2/queue")) {
                expect(path).toContain("run_id=run-123");
                return Promise.resolve(data as any);
            }
            if (path.includes("consistency-checks/list")) return Promise.resolve({ items: [] } as any);
            if (path.includes("/accounts/processing/summary")) {
                return Promise.resolve({ pending_count: 0, pending_total: "0.00", currency: "SGD", oldest_pending_date: null } as any);
            }
            if (path.includes("batch-approve-matches")) {
                expect(JSON.parse(String(options?.body))).toEqual({ match_ids: ["m1", "m2"], run_id: "run-123" });
                return Promise.resolve({ success: true, approved_count: 2 } as any);
            }
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<RunReviewPage /> as any);

        const approveRun = await screen.findByRole("button", { name: /Approve Run/i });
        expect(approveRun).toBeEnabled();
        fireEvent.click(approveRun);

        await waitFor(() => {
            expect(mockedApi.mock.calls.some((call) => String(call[0]).includes("batch-approve-matches"))).toBe(true);
        });
    });
});
