import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import AuditPage from "@/app/(main)/audit/page";
import { apiOperation } from "@/lib/api-client";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => new URLSearchParams("run_id=run-123")),
    usePathname: vi.fn(() => "/audit"),
}));

function mapStage2OperationToLegacy(operationId: string, req: any = {}): [string, RequestInit | undefined] {
    switch (operationId) {
        case "get_stage2_review_queue_statements_stage2_queue_get": {
            const q = req?.query;
            let path = "/api/statements/stage2/queue";
            if (q) {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(q)) {
                    if (v !== undefined && v !== null) params.append(k, String(v));
                }
                const qs = params.toString();
                if (qs) path += `?${qs}`;
            }
            return [path, undefined];
        }
        case "list_consistency_checks_statements_consistency_checks_list_get":
            return ["/api/statements/consistency-checks/list", undefined];
        case "batch_approve_matches_statements_batch_approve_matches_post":
            return ["/api/statements/batch-approve-matches", { method: "POST", body: JSON.stringify(req?.body) }];
        case "get_processing_summary_accounts_processing_summary_get":
            return ["/api/accounts/processing/summary", undefined];
        default:
            return [operationId, req];
    }
}

const mockedApi = vi.mocked(apiOperation);
const originalMockImplementation = mockedApi.mockImplementation.bind(mockedApi);
mockedApi.mockImplementation = (fn: any) => {
    return originalMockImplementation((operationId: any, req: any) => {
        if (typeof operationId === "string" && operationId.startsWith("/")) {
            return fn(operationId, req);
        }
        const [path, options] = mapStage2OperationToLegacy(operationId, req);
        return fn(path, options);
    });
};

describe("Run-scoped review on /audit", () => {
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
                    pending_matches: [{ id: "m1", match_score: 90, confidence_tier: "HIGH", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Transfer" }],
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

        renderReviewComponent(<AuditPage /> as any);

        expect(await screen.findByRole("heading", { name: "Review this reconciliation run" })).toBeInTheDocument();
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
                { id: "m1", match_score: 95, confidence_tier: "HIGH", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Bank A out" },
                { id: "m2", match_score: 92, confidence_tier: "HIGH", status: "pending", amount: "10", txn_date: "2024-01-02", description: "Bank B in" },
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

        renderReviewComponent(<AuditPage /> as any);

        const approveRun = await screen.findByRole("button", { name: /Approve Run/i });
        expect(approveRun).toBeEnabled();
        fireEvent.click(approveRun);

        await waitFor(() => {
            expect(mockedApi.mock.calls.some((call) => String(call[0]).includes("batch_approve_matches") || String(call[0]).includes("batch-approve-matches"))).toBe(true);
        });
    });
});
